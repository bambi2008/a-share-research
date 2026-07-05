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
                if progress_callback:
                    progress_callback(f"  分红缓存: {len(cache)-1} 只")
                return cache
        except Exception:
            pass

    # 缓存不可用 → 不联网获取，直接返回空（避免卡死）
    if progress_callback:
        progress_callback("  分红: 缓存不可用，跳过（需首次联网获取）")
    return {}


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
        div_yield = round(info["avg_div"] / price * 100, 2)

    return {
        "avg_div": info["avg_div"],
        "div_count": info["div_count"],
        "div_yield": div_yield,
    }
