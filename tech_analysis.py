#!/usr/bin/env python3
"""
技术面趋势分析 — 对候选池做均线/RSI快速评估
数据源: 新浪 stock_zh_a_daily (Windows兼容)
"""
import concurrent.futures


def compute_indicators(close_prices):
    """从收盘价序列计算技术指标。
    close_prices: list of float, 最近120天，按时间升序
    返回: {ma20, ma60, above_ma20, above_ma60, rsi14, trend, trend_strength}
    """
    if len(close_prices) < 60:
        return None

    # MA
    ma20 = sum(close_prices[-20:]) / 20
    ma60 = sum(close_prices[-60:]) / 60
    latest = close_prices[-1]
    above_ma20 = latest > ma20
    above_ma60 = latest > ma60

    # RSI(14)
    gains = []
    losses = []
    for i in range(-14, 0):
        diff = close_prices[i] - close_prices[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        rsi = 100
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

    # 趋势方向：最近20天 vs 前20天
    recent_20 = sum(close_prices[-20:]) / 20
    prior_20 = sum(close_prices[-40:-20]) / 20
    if prior_20 == 0:
        trend_strength = 0
    else:
        trend_strength = (recent_20 / prior_20 - 1) * 100

    if trend_strength > 3:
        trend = "up"
    elif trend_strength < -3:
        trend = "down"
    else:
        trend = "flat"

    return {
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "above_ma20": above_ma20,
        "above_ma60": above_ma60,
        "rsi14": round(rsi, 1),
        "trend": trend,
        "trend_strength": round(trend_strength, 1),
    }


def fetch_one_stock(code, timeout=10):
    """获取单只股票的日线数据"""
    import akshare as ak
    try:
        # sh/sz prefix
        if code.startswith(("60", "68", "90")):
            symbol = f"sh{code}"
        elif code.startswith(("00", "30", "20")):
            symbol = f"sz{code}"
        elif code.startswith(("8", "4", "92")):
            symbol = f"bj{code}"
        else:
            symbol = f"sz{code}"

        df = ak.stock_zh_a_daily(symbol=symbol, start_date="20250801", adjust="qfq")
        if df is None or len(df) < 60:
            return None
        closes = [float(c) for c in df["close"].values]
        return compute_indicators(closes)
    except Exception:
        return None


def analyze_candidates(candidates, progress_callback=None, max_workers=5):
    """对候选池批量获取技术指标。只对TOP候选做（避免全市场请求）。
    返回: {code: indicators_dict}
    """
    results = {}
    # 只分析前30只
    top = candidates[:30]
    total = len(top)

    def _fetch_one(c):
        code = c.get("code", "")
        name = c.get("name", "")
        if progress_callback:
            progress_callback(f"技术面 {len(results)+1}/{total}: {name}")
        return code, fetch_one_stock(code)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, c): c for c in top}
        for fut in concurrent.futures.as_completed(futures):
            try:
                code, ind = fut.result(timeout=15)
                if ind:
                    results[code] = ind
            except Exception:
                pass

    if progress_callback:
        up = sum(1 for v in results.values() if v.get("trend") == "up")
        down = sum(1 for v in results.values() if v.get("trend") == "down")
        progress_callback(f"技术面: {up}↑ {down}↓ (共{len(results)}只)")

    return results


def trend_summary(code, indicators):
    """生成单只股票的技术面摘要文本"""
    if not indicators:
        return ""
    ind = indicators
    parts = []
    if ind.get("above_ma60"):
        parts.append("站上MA60")
    else:
        parts.append("跌破MA60")
    parts.append(f"RSI{ind.get('rsi14',0):.0f}")
    trend = ind.get("trend", "")
    trend_map = {"up": "↑", "down": "↓", "flat": "→"}
    parts.append(trend_map.get(trend, trend))
    return " ".join(parts)
