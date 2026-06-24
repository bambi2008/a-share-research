#!/usr/bin/env python3
"""
持仓跟踪模块
存 holdings.json 在 app 目录，scanner 扫描时自动展示持仓盈亏。
"""
import json
import os
import sys


STOP_LOSS_PCT = -0.20   # 止损 -20%
TAKE_PROFIT_PCT = 0.50  # 止盈 +50%


def _app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def holdings_path():
    return os.path.join(_app_dir(), "holdings.json")


def load_holdings():
    path = holdings_path()
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_holdings(holdings):
    with open(holdings_path(), 'w', encoding='utf-8') as f:
        json.dump(holdings, f, ensure_ascii=False, indent=2)


def add_position(code, name, cost, date, notes=""):
    """添加持仓。cost=成本价(元/股), date='2026-06-15'"""
    h = load_holdings()
    h[code] = {"name": name, "cost": cost, "date": date, "notes": notes}
    save_holdings(h)


def remove_position(code):
    h = load_holdings()
    h.pop(code, None)
    save_holdings(h)


def check_positions(price_map, code_name_map=None):
    """
    对持仓做体检。price_map: {code: current_price}
    返回 (positions, alerts) 列表
    """
    h = load_holdings()
    if not h:
        return [], []

    positions = []
    alerts = []
    for code, info in h.items():
        price = price_map.get(code)
        cost = info.get("cost", 0)
        name = info.get("name", code_name_map.get(code, "") if code_name_map else "")
        if price and cost > 0:
            pnl = (price - cost) / cost * 100
        else:
            pnl = None

        pos = {
            "code": code,
            "name": name,
            "cost": cost,
            "price": price,
            "pnl_pct": pnl,
            "date": info.get("date", ""),
            "alerts": [],
        }

        if pnl is not None:
            if pnl <= STOP_LOSS_PCT * 100:
                pos["alerts"].append(f"🔴 止损 (-{abs(STOP_LOSS_PCT*100):.0f}%)")
            elif pnl >= TAKE_PROFIT_PCT * 100:
                pos["alerts"].append(f"🟢 止盈 (+{TAKE_PROFIT_PCT*100:.0f}%)")

        positions.append(pos)

    return positions, alerts
