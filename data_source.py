#!/usr/bin/env python3
"""
多源数据容灾层
主源(新浪/巨潮) → 失败 → 备用(baostock) → 失败 → 本地缓存
每次返回标注数据来源 + 新鲜度
"""
import akshare as ak
import baostock as bs
import json, os, sys, time
from datetime import datetime


def _app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CACHE_DIR = os.path.join(_app_dir(), "data_cache")
CACHE_TTL = 3600  # 缓存有效期(秒)

# ── 缓存层 ──
def _cache_get(key):
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        age = time.time() - data.get("_ts", 0)
        if age > CACHE_TTL:
            return None  # 过期
        return data
    except Exception:
        return None


def _cache_set(key, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    data["_ts"] = time.time()
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


# ── 股票行情 ──
def get_price_map(timeout=30):
    """获取 A 股实时行情 {code: price}。
    主源: 新浪 stock_zh_a_spot
    备用: baostock query_stock_industry + query_history_k_data_plus
    """
    # 先查缓存
    cached = _cache_get("price_map")
    if cached:
        return cached.get("data", {}), "缓存"

    # 主源: 新浪
    try:
        df = ak.stock_zh_a_spot()
        result = {}
        for _, row in df.iterrows():
            code = str(row['代码']).replace('bj', '').replace('sh', '').replace('sz', '')
            result[code] = float(row['最新价'])
        _cache_set("price_map", {"data": result})
        return result, "新浪"
    except Exception:
        pass

    # 备用: baostock (只取沪深两市)
    try:
        bs.login()
        # 取最近交易日
        rs = bs.query_trade_dates(start_date=(datetime.now().strftime('%Y-%m-%d')))
        dates = []
        while rs.next(): dates.append(rs.get_row_data()[0])
        bs.logout()
        # 取最近一个交易日的数据
        trade_date = dates[-1] if dates else datetime.now().strftime('%Y-%m-%d')

        result = {}
        # 沪深300作为采样(太多股票baostock会慢)
        bs.login()
        for market in ['sh', 'sz']:
            # 沪深所有股票太多，取沪深300成分股 + 创业板
            stock_list = []
            # 沪深300
            rs = bs.query_hs300_stocks()
            while rs.next(): stock_list.append(rs.get_row_data()[0].replace('sh.', '').replace('sz.', ''))
            # 创业板成分
            rs = bs.query_sz50_stocks()
            while rs.next(): stock_list.append(rs.get_row_data()[0].replace('sh.', '').replace('sz.', ''))

            # 去重并取最近收盘价
            for code in list(set(stock_list))[:800]:
                rs = bs.query_history_k_data_plus(
                    f"{'sh' if code.startswith('6') else 'sz'}.{code}",
                    "date,close", start_date=trade_date, end_date=trade_date
                )
                while rs.next():
                    row = rs.get_row_data()
                    try:
                        result[code] = float(row[1])
                    except Exception:
                        pass
        bs.logout()
        if result:
            _cache_set("price_map", {"data": result})
            return result, "baostock(备用)"
    except Exception:
        pass

    return {}, "全部失败"


# ── 指数数据 ──
def get_index_data(timeout=30):
    """获取三大指数最新数据。返回 {name: {close, chg_pct, date}}。
    主源: 新浪 stock_zh_index_daily
    备用: baostock query_history_k_data_plus
    """
    import scanner
    cached = _cache_get("index_data")
    if cached:
        return cached.get("data", {}), "缓存"

    result = {}
    # 主源: 新浪
    all_ok = True
    for name, sym in scanner.INDICES:
        try:
            df = ak.stock_zh_index_daily(symbol=sym)
            latest = df.iloc[-1]
            prev = df.iloc[-6] if len(df) >= 6 else df.iloc[0]
            close = float(latest['close'])
            chg = (close - float(prev['close'])) / float(prev['close']) * 100
            result[name] = {"close": close, "chg_pct": chg, "date": str(latest['date'])[:10]}
        except Exception:
            all_ok = False

    if all_ok and result:
        _cache_set("index_data", {"data": result})
        return result, "新浪"

    # 备用: baostock
    baostock_map = {
        "上证指数": "sh.000001", "创业板指": "sz.399006", "科创50": "sh.000688"
    }
    try:
        bs.login()
        for name, bcode in baostock_map.items():
            if name in result and result[name].get("close"):
                continue
            rs = bs.query_history_k_data_plus(bcode, "date,close", 
                start_date=(datetime.now() - __import__('datetime').timedelta(days=30)).strftime('%Y-%m-%d'),
                end_date=datetime.now().strftime('%Y-%m-%d'))
            rows = []
            while rs.next(): rows.append(rs.get_row_data())
            if len(rows) >= 6:
                result[name] = {
                    "close": float(rows[-1][1]),
                    "chg_pct": (float(rows[-1][1]) - float(rows[-6][1])) / float(rows[-6][1]) * 100,
                    "date": rows[-1][0]
                }
        bs.logout()
        source = "baostock(备用)" if result else "全部失败"
    except Exception:
        source = "全部失败"

    if result:
        _cache_set("index_data", {"data": result})
    return result, source


# ── 市值数据(单只) ──
def get_mktcap(ak_module, code, timeout=20):
    """获取单只股票流通市值。主源: 新浪日线 outstanding_share × close
    备用: baostock
    """
    import scanner
    # 主源: 新浪（复用已有逻辑）
    mv = scanner._fetch_float_mktcap(ak_module, code)
    if mv is not None:
        return mv, "新浪"

    # 备用: baostock
    prefix = 'sh' if code.startswith(('60','68','90','11','51')) else 'sz'
    try:
        bs.login()
        rs = bs.query_stock_basic(code=f"{prefix}.{code}")
        if rs.next():
            shares = float(rs.get_row_data()[2]) if len(rs.get_row_data()) > 2 else 0
        else:
            bs.logout()
            return None, "全部失败"

        rs = bs.query_history_k_data_plus(f"{prefix}.{code}", "date,close",
            start_date=datetime.now().strftime('%Y-%m-%d'),
            end_date=datetime.now().strftime('%Y-%m-%d'))
        price = None
        while rs.next():
            try: price = float(rs.get_row_data()[1])
            except: pass
        bs.logout()
        if shares > 0 and price:
            return price * shares / 1e8, "baostock(备用)"
    except Exception:
        pass
    return None, "全部失败"


# ── 健康报告 ──
def health_report():
    """返回各数据源健康状态"""
    report = {"price_map": None, "index_data": None, "mktcap": None}
    try:
        _, src = get_price_map(timeout=15)
        report["price_map"] = src
    except Exception:
        report["price_map"] = "失败"

    try:
        _, src = get_index_data(timeout=15)
        report["index_data"] = src
    except Exception:
        report["index_data"] = "失败"

    # 市值测试
    try:
        import scanner
        mv, src = get_mktcap(ak, "600519", timeout=10)
        report["mktcap"] = src
    except Exception:
        report["mktcap"] = "失败"

    return report
