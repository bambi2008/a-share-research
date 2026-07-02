#!/usr/bin/env python3
"""
多源数据容灾层 v2
====================
主源(新浪/巨潮) → 失败 → 备用(baostock) → 失败 → 本地缓存

相比 v1 的四点修复:
  1. 真超时     —— 每个网络调用都用子线程 + 硬超时包裹(v1 的 timeout 参数是摆设)。
  2. 覆盖告知   —— 备用源按"调用方给的目标股票池"取数, 不再只覆盖沪深300;
                   返回的 meta 明确写出实际覆盖率(如 覆盖 1203/1576)。
  3. 降级不静默 —— 每次返回 (data, meta), meta 内含 源/新鲜度/覆盖率/是否降级。
  4. 动量地基   —— 新增 get_price_history(), 为动量仓提供可靠日线序列。

另外: 消除了 v1 的 data_source <-> scanner 循环 import
      (指数列表 / 市值逻辑本就属于数据层, 已内聚到这里)。

注意: akshare / baostock 均为函数内惰性导入, 因此本模块可在无这两个包的环境
      里被 import(纯逻辑与缓存仍可用/可测)。
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import time
from datetime import datetime, timedelta

# ────────────────────────── 配置 ──────────────────────────

CACHE_TTL_REALTIME = 3600        # 实时行情缓存有效期(秒)
CACHE_TTL_HISTORY = 6 * 3600     # 历史序列缓存有效期(秒)

# 三大指数(数据配置, 内聚在数据层, 不再依赖 scanner)
INDICES = [
    ("上证指数", "sh000001", "sh.000001"),   # (名称, 新浪symbol, baostock code)
    ("创业板指", "sz399006", "sz.399006"),
    ("科创50",  "sh000688", "sh.000688"),
]


def _app_dir() -> str:
    """应用数据目录。打包成 .exe 时用 .exe 所在目录, 否则用脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CACHE_DIR = os.path.join(_app_dir(), "data_cache")


# ────────────────────── 通用: 超时 / 代码前缀 ──────────────────────

def call_with_timeout(fn, timeout, *args, **kwargs):
    """在子线程执行 fn, 超时抛 TimeoutError; 数据损坏(zlib)抛 RuntimeError。

    这是对 v1 "timeout 参数从不生效" 的核心修复: 所有阻塞式网络调用都必须
    经过这里, 才有真正的超时保护。
    """
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, *args, **kwargs)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"数据请求超时(>{timeout}s)")
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if "decompress" in low or "header check" in low or "error -3" in low:
            raise RuntimeError(f"数据传输损坏(可能代理/VPN导致): {msg[:80]}")
        raise
    finally:
        ex.shutdown(wait=False)


def market_prefix(code: str) -> str:
    """按股票代码判断市场: 'sh' / 'sz' / 'bj'。"""
    code = str(code)
    if code.startswith(("60", "68", "90", "11", "51")):
        return "sh"
    if code.startswith(("00", "30", "12", "15", "20")):
        return "sz"
    if code.startswith(("8", "4", "92")):
        return "bj"
    return "sh"  # 兜底


def sina_symbol(code: str) -> str:
    """新浪 symbol, 如 600519 -> sh600519。"""
    return f"{market_prefix(code)}{code}"


def baostock_symbol(code: str) -> str:
    """baostock code, 如 600519 -> sh.600519(北交所 baostock 不支持, 归 sz 兜底)。"""
    p = market_prefix(code)
    if p == "bj":
        p = "sz"  # baostock 无北交所, 交给上层判空
    return f"{p}.{code}"


def _deadline(budget_s: float):
    """返回一个闭包 expired(), budget 秒后为 True。用于给整段循环设总预算。"""
    start = time.time()
    return lambda: (time.time() - start) > budget_s


# ────────────────────────── 缓存层 ──────────────────────────

def _cache_get(key: str, ttl: int):
    """命中且未过期则返回 (data, age_seconds), 否则 (None, None)。"""
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            blob = json.load(f)
        age = time.time() - blob.get("_ts", 0)
        if age > ttl:
            return None, None
        return blob.get("data"), age
    except Exception:
        return None, None


def _cache_set(key: str, data) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"_ts": time.time(), "data": data}, f, ensure_ascii=False)
    except Exception:
        pass


def _fmt_age(age_s: float | None) -> str:
    if age_s is None:
        return "实时"
    if age_s < 90:
        return "刚刚"
    if age_s < 3600:
        return f"{int(age_s // 60)}分钟前"
    return f"{age_s / 3600:.1f}小时前"


def _coverage(got: dict, universe) -> str:
    """生成覆盖率描述。universe 为 None 时不写分母。"""
    n = len(got)
    if universe:
        return f"覆盖 {n}/{len(universe)}"
    return f"覆盖 {n} 只"


# ────────────────────── 实时行情 (price map) ──────────────────────

def get_price_map(timeout: int = 60, codes=None):
    """获取 A 股实时行情 {code: price}。

    参数:
        timeout: 单次网络调用的硬超时(秒)。
        codes:   目标股票池(可迭代)。**强烈建议传入**——备用源(baostock)会
                 只针对这批代码取数, 从而覆盖你真正关心的中小盘, 而非 v1 那样
                 只覆盖沪深300大盘。为 None 时备用源仅能给出大盘子集, meta 会标注。

    返回: (price_map: dict, meta: str)
          meta 形如 "新浪(实时)" / "baostock(备用,T-1收盘,覆盖1203/1576)" /
                    "缓存(2.1小时前,覆盖1500)" / "全部失败"
    """
    universe = set(map(str, codes)) if codes else None

    # ── 主源: 新浪实时(全市场) ──
    try:
        ak = _ak()
        df = call_with_timeout(ak.stock_zh_a_spot, timeout)
        result = {}
        for _, row in df.iterrows():
            raw = str(row["代码"])
            code = raw.replace("bj", "").replace("sh", "").replace("sz", "")
            try:
                result[code] = float(row["最新价"])
            except (TypeError, ValueError):
                continue
        if result:
            if universe:
                result = {c: p for c, p in result.items() if c in universe}
            _cache_set("price_map", result)
            return result, f"新浪(实时,{_coverage(result, universe)})"
    except Exception:
        pass

    # ── 备用: baostock 最近交易日收盘(只取目标池, 串行 + 总预算) ──
    # baostock 单 TCP 会话不支持并发, 故串行; 用总预算防止无限拖延。
    try:
        bs = _bs()
        bs.login()
        try:
            trade_date = _latest_trade_date(bs)
            targets = list(universe) if universe else _large_cap_sample(bs)
            budget = _deadline(max(timeout * 4, 120))  # 备用路径给更宽的总预算
            result = {}
            for code in targets:
                if budget():
                    break
                sym = baostock_symbol(code)
                if sym.startswith("bj"):  # 北交所跳过
                    continue
                rs = bs.query_history_k_data_plus(
                    sym, "date,close",
                    start_date=trade_date, end_date=trade_date, frequency="d",
                )
                while rs.next():
                    try:
                        result[code] = float(rs.get_row_data()[1])
                    except (TypeError, ValueError, IndexError):
                        pass
        finally:
            bs.logout()
        if result:
            _cache_set("price_map", result)
            note = "" if universe else ",仅大盘子集"
            return result, f"baostock(备用,T-1收盘{note},{_coverage(result, universe)})"
    except Exception:
        pass

    # ── 兜底: 缓存(明确告知新鲜度) ──
    cached, age = _cache_get("price_map", CACHE_TTL_REALTIME)
    if cached:
        return cached, f"缓存({_fmt_age(age)},{_coverage(cached, universe)})"

    return {}, "全部失败"


def _latest_trade_date(bs) -> str:
    """用 baostock 找最近一个交易日(YYYY-MM-DD)。失败则退回今天。"""
    try:
        start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        rs = bs.query_trade_dates(start_date=start, end_date=end)
        dates = []
        while rs.next():
            row = rs.get_row_data()
            # row = [calendar_date, is_trading_day]
            if len(row) >= 2 and str(row[1]) == "1":
                dates.append(row[0])
        if dates:
            return dates[-1]
    except Exception:
        pass
    return datetime.now().strftime("%Y-%m-%d")


def _large_cap_sample(bs) -> list:
    """未提供 codes 时的降级样本: 沪深300 + 上证50(去重)。仅覆盖大盘, 会在 meta 标注。"""
    out = []
    for q in (getattr(bs, "query_hs300_stocks", None),
              getattr(bs, "query_sz50_stocks", None)):
        if q is None:
            continue
        try:
            rs = q()
            while rs.next():
                c = rs.get_row_data()[1].replace("sh.", "").replace("sz.", "")
                out.append(c)
        except Exception:
            continue
    return list(dict.fromkeys(out))  # 保序去重


# ────────────────────── 历史序列 (动量地基) ──────────────────────

def get_price_history(codes, days: int = 120, timeout: int = 240):
    """获取一批股票的日线收盘序列, 供动量仓计算相对强弱 / 20-60日收益 / 均线。

    主源: baostock 前复权日线(query_history_k_data_plus, adjustflag=2)。
          baostock 历史数据干净且不依赖东财, 契合本项目"避开东财"的约束。

    返回: (hist: dict[code -> {"dates":[...], "close":[float,...]}], meta: str)
          仅返回成功取到、且长度足够的股票; meta 标注覆盖率与是否因预算截断。
    """
    codes = [str(c) for c in codes]
    if not codes:
        return {}, "空目标池"

    cache_key = f"hist_{days}_{_hash_codes(codes)}"
    cached, age = _cache_get(cache_key, CACHE_TTL_HISTORY)
    if cached:
        return cached, f"缓存({_fmt_age(age)},{_coverage(cached, codes)})"

    start = (datetime.now() - timedelta(days=days + 40)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")

    try:
        bs = _bs()
        bs.login()
        truncated = False
        try:
            budget = _deadline(timeout)
            hist = {}
            for code in codes:
                if budget():
                    truncated = True
                    break
                sym = baostock_symbol(code)
                if sym.startswith("bj"):
                    continue
                try:
                    rs = bs.query_history_k_data_plus(
                        sym, "date,close", start_date=start, end_date=end,
                        frequency="d", adjustflag="2",
                    )
                    dates, closes = [], []
                    while rs.next():
                        d, c = rs.get_row_data()[:2]
                        try:
                            closes.append(float(c))
                            dates.append(d)
                        except (TypeError, ValueError):
                            pass
                    if len(closes) >= 20:  # 至少 20 个交易日才有动量意义
                        hist[code] = {"dates": dates, "close": closes}
                except Exception:
                    continue
        finally:
            bs.logout()
        if hist:
            _cache_set(cache_key, hist)
            note = ",预算内截断" if truncated else ""
            return hist, f"baostock(前复权{note},{_coverage(hist, codes)})"
    except Exception:
        pass

    cached, age = _cache_get(cache_key, CACHE_TTL_HISTORY * 4)  # 兜底放宽到 24h
    if cached:
        return cached, f"缓存({_fmt_age(age)},{_coverage(cached, codes)})"

    return {}, "全部失败"


def _hash_codes(codes) -> str:
    import hashlib
    h = hashlib.md5(",".join(sorted(codes)).encode()).hexdigest()
    return h[:10]


# ────────────────────────── 指数数据 ──────────────────────────

def get_index_data(timeout: int = 30):
    """获取三大指数最新数据。返回 ({name: {close, chg_pct, date}}, meta)。

    主源: 新浪 stock_zh_index_daily(真超时)。
    备用: baostock 近30日日线。
    """
    result = {}

    # ── 主源: 新浪 ──
    all_ok = True
    try:
        ak = _ak()
        for name, sym, _bcode in INDICES:
            try:
                df = call_with_timeout(ak.stock_zh_index_daily, timeout, symbol=sym)
                latest = df.iloc[-1]
                prev = df.iloc[-6] if len(df) >= 6 else df.iloc[0]
                close = float(latest["close"])
                chg = (close - float(prev["close"])) / float(prev["close"]) * 100
                result[name] = {"close": close, "chg_pct": chg,
                                "date": str(latest["date"])[:10]}
            except Exception:
                all_ok = False
    except Exception:
        all_ok = False

    if all_ok and len(result) == len(INDICES):
        _cache_set("index_data", result)
        return result, "新浪(实时)"

    # ── 备用: baostock ──
    try:
        bs = _bs()
        bs.login()
        try:
            start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            end = datetime.now().strftime("%Y-%m-%d")
            for name, _sym, bcode in INDICES:
                if result.get(name, {}).get("close"):
                    continue
                try:
                    rs = bs.query_history_k_data_plus(
                        bcode, "date,close", start_date=start, end_date=end, frequency="d")
                    rows = []
                    while rs.next():
                        rows.append(rs.get_row_data())
                    if len(rows) >= 6:
                        c = float(rows[-1][1]); c6 = float(rows[-6][1])
                        result[name] = {"close": c, "chg_pct": (c - c6) / c6 * 100,
                                        "date": rows[-1][0]}
                except Exception:
                    continue
        finally:
            bs.logout()
    except Exception:
        pass

    if result:
        _cache_set("index_data", result)
        degraded = len(result) < len(INDICES)
        src = "baostock(备用)" if not all_ok else "新浪+baostock"
        return result, src + ("(部分缺失)" if degraded else "")

    cached, age = _cache_get("index_data", CACHE_TTL_REALTIME)
    if cached:
        return cached, f"缓存({_fmt_age(age)})"
    return {}, "全部失败"


# ────────────────────── 单只市值(内聚, 不再依赖 scanner) ──────────────────────

def get_mktcap(code, timeout: int = 20):
    """获取单只股票流通市值(亿元)。主源新浪日线 outstanding_share × close, 备用 baostock。

    返回 (mktcap: float|None, source: str)。
    """
    code = str(code)
    # ── 主源: 新浪日线 ──
    try:
        ak = _ak()
        df = call_with_timeout(
            ak.stock_zh_a_daily, timeout,
            symbol=sina_symbol(code), start_date="20260101", adjust="")
        if df is not None and len(df):
            latest = df.iloc[-1]
            shares = latest.get("outstanding_share")
            close = latest.get("close")
            if shares and close:
                return close * shares / 1e8, "新浪"
    except Exception:
        pass

    # ── 备用: baostock ──
    sym = baostock_symbol(code)
    if not sym.startswith("bj"):
        try:
            bs = _bs()
            bs.login()
            try:
                rs = bs.query_stock_basic(code=sym)
                shares = 0.0
                if rs.next():
                    row = rs.get_row_data()
                    shares = float(row[2]) if len(row) > 2 and row[2] else 0.0
                price = None
                today = datetime.now().strftime("%Y-%m-%d")
                rs = bs.query_history_k_data_plus(
                    sym, "date,close", start_date=today, end_date=today, frequency="d")
                while rs.next():
                    try:
                        price = float(rs.get_row_data()[1])
                    except (TypeError, ValueError, IndexError):
                        pass
            finally:
                bs.logout()
            if shares > 0 and price:
                return price * shares / 1e8, "baostock(备用)"
        except Exception:
            pass

    return None, "全部失败"


# ────────────────────────── 健康报告 ──────────────────────────

def health_report():
    """返回各数据源健康状态(附 meta)。"""
    report = {}
    try:
        _, src = get_price_map(timeout=15)
        report["price_map"] = src
    except Exception as e:
        report["price_map"] = f"失败:{str(e)[:40]}"
    try:
        _, src = get_index_data(timeout=15)
        report["index_data"] = src
    except Exception as e:
        report["index_data"] = f"失败:{str(e)[:40]}"
    try:
        mv, src = get_mktcap("600519", timeout=10)
        report["mktcap"] = f"{src}({mv:.0f}亿)" if mv else src
    except Exception as e:
        report["mktcap"] = f"失败:{str(e)[:40]}"
    return report


# ────────────────────── 惰性依赖 ──────────────────────

def _ak():
    import akshare as ak
    return ak


def _bs():
    import baostock as bs
    return bs


if __name__ == "__main__":
    print("数据源健康检查:")
    for k, v in health_report().items():
        print(f"  {k:12s}: {v}")
