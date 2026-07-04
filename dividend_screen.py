#!/usr/bin/env python3
"""
分红率筛选 — 基于 stock_history_dividend 补充候选股分红数据
"""
import json, os, sys, time


def _cache_path():
    d = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, 'frozen', False):
        d = os.path.dirname(sys.executable)
    return os.path.join(d, ".dividend_cache.json")


def fetch_dividend_data(progress_callback=None, force_refresh=False):
    """获取全A股分红历史汇总。24h缓存。
    返回: {code: {name, total_div, years, avg_div, div_freq, div_yield}}
    """
    cp = _cache_path()

    if not force_refresh and os.path.exists(cp):
        try:
            cache = json.load(open(cp, 'r', encoding='utf-8'))
            if time.time() - cache.get("_ts", 0) < 86400:
                return cache
        except Exception:
            pass

    def log(msg):
        if progress_callback:
            progress_callback(msg)

    import akshare as ak
    log("分红数据: 同花顺...")

    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(ak.stock_history_dividend)
            df = fut.result(timeout=15)
        log(f"  分红: {len(df)} 只股票")
    except Exception as e:
        log(f"  分红跳过: {e}")
        return {}

    result = {}
    for _, row in df.iterrows():
        try:
            code = str(row.get("代码", ""))
            if not code or len(code) < 6:
                continue
            name = row.get("名称", "")
            total_div = float(row.get("累计股息", 0))
            avg_div = float(row.get("年均股息", 0))
            div_count = int(row.get("分红次数", 0))

            result[code] = {
                "name": str(name),
                "total_div": round(total_div, 1),
                "avg_div": round(avg_div, 2),
                "div_count": div_count,
            }
        except Exception:
            continue

    result["_ts"] = time.time()
    try:
        json.dump(result, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception:
        pass

    log(f"  有效: {len(result)-1} 只")
    return result


def get_dividend_info(code, dividend_data, price=None):
    """获取单只股票的分红信息。
    返回: dict 或 None
    """
    if not dividend_data:
        return None
    info = dividend_data.get(code)
    if not info:
        return None

    div_yield = None
    if price and price > 0 and info.get("avg_div", 0) > 0:
        div_yield = round(info["avg_div"] / price * 100, 1)

    return {
        "avg_div": info["avg_div"],
        "div_count": info["div_count"],
        "div_yield": div_yield,
    }
