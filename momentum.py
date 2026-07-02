#!/usr/bin/env python3
"""
动量扫描 (A 动量弹性仓)
=======================
基于日线收盘序列计算动量指标, 用于短中期趋势/主题轮动选股。

指标数学全部为纯函数(输入收盘序列, 无网络), 可精确单测。
扫描编排 scan_momentum() 依赖 data_source.get_price_history() 取数。

约定: closes 为按时间升序的收盘价列表(最早 → 最新)。
"""
from __future__ import annotations


def ret(closes, n: int):
    """N 个交易日收益率(小数)。长度不足返回 None。"""
    if closes is None or len(closes) <= n or closes[-1 - n] == 0:
        return None
    return closes[-1] / closes[-1 - n] - 1.0


def sma(closes, n: int):
    """最近 N 日简单均线。长度不足返回 None。"""
    if closes is None or len(closes) < n or n <= 0:
        return None
    return sum(closes[-n:]) / n


def above_sma(closes, n: int):
    """现价是否站上 N 日均线。数据不足返回 None。"""
    m = sma(closes, n)
    if m is None or not closes:
        return None
    return closes[-1] > m


def relative_strength(stock_closes, index_closes, n: int):
    """相对强弱: 个股 N 日收益 − 指数 N 日收益(小数)。任一不足返回 None。"""
    rs, ri = ret(stock_closes, n), ret(index_closes, n)
    if rs is None or ri is None:
        return None
    return rs - ri


def momentum_score(closes, index_closes=None):
    """复合动量分(越高越强)。返回 (score, components)。

    组成(可解释、非黑箱):
      0.6 × 20日收益 + 0.4 × 60日收益
      + 站上 20日均线 +0.02, 站上 60日均线 +0.02
      + (可选)相对指数强度 20日 × 0.3
    数据不足的分项按 0 计, 但会在 components 里标注 None 以便甄别。
    """
    r20, r60 = ret(closes, 20), ret(closes, 60)
    a20, a60 = above_sma(closes, 20), above_sma(closes, 60)
    comp = {"ret20": r20, "ret60": r60, "above_ma20": a20, "above_ma60": a60,
            "rs20": None}

    score = 0.6 * (r20 or 0.0) + 0.4 * (r60 or 0.0)
    if a20:
        score += 0.02
    if a60:
        score += 0.02
    if index_closes is not None:
        rs20 = relative_strength(closes, index_closes, 20)
        comp["rs20"] = rs20
        if rs20 is not None:
            score += 0.3 * rs20

    return score, comp


def rank_momentum(hist: dict, index_closes=None, min_len: int = 60):
    """对 {code: {"close":[...]}} 计算动量分并降序排列。

    返回 [{code, score, ret20, ret60, above_ma20, above_ma60, rs20}, ...]。
    序列长度 < min_len 的股票跳过(动量信号不可靠)。
    """
    rows = []
    for code, series in hist.items():
        closes = series.get("close") if isinstance(series, dict) else series
        if not closes or len(closes) < min_len:
            continue
        score, comp = momentum_score(closes, index_closes)
        rows.append({"code": code, "score": score, **comp})
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows


def scan_momentum(codes, top_n: int = 15, index_symbol_closes=None,
                  data_source_mod=None):
    """动量扫描编排(需联网): 拉历史 → 排名 → 取前 top_n。

    返回 (ranked_rows, meta)。data_source_mod 用于注入/测试。
    """
    if data_source_mod is None:
        import data_source as data_source_mod
    hist, meta = data_source_mod.get_price_history(codes, days=120)
    ranked = rank_momentum(hist, index_closes=index_symbol_closes)
    return ranked[:top_n], meta
