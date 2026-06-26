#!/usr/bin/env python3
"""
投资记录本 — 记录买卖、计算盈亏、追踪总资产
存储: portfolio.json（与 exe 同目录）
"""
import json, os, sys
from datetime import datetime


def _app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def _path():
    return os.path.join(_app_dir(), "portfolio.json")


def load():
    if not os.path.exists(_path()):
        return {"cash": 100000, "trades": [], "holdings": {}}
    with open(_path(), 'r', encoding='utf-8') as f:
        return json.load(f)

def save(data):
    with open(_path(), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def buy(code, name, price, shares, date=None):
    """买入记录"""
    data = load()
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    cost = price * shares
    data["cash"] -= cost
    trade = {
        "type": "buy", "code": code, "name": name,
        "price": price, "shares": shares, "cost": cost, "date": date
    }
    data["trades"].append(trade)
    h = data["holdings"].get(code, {"shares": 0, "cost_basis": 0, "name": name})
    total_cost = h["cost_basis"] + cost
    total_shares = h["shares"] + shares
    data["holdings"][code] = {
        "shares": total_shares, "cost_basis": total_cost,
        "avg_cost": total_cost / total_shares if total_shares > 0 else 0,
        "name": name
    }
    save(data)
    return trade


def sell(code, price, shares, date=None):
    """卖出记录"""
    data = load()
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    h = data["holdings"].get(code)
    if not h or h["shares"] < shares:
        return None
    revenue = price * shares
    data["cash"] += revenue
    trade = {
        "type": "sell", "code": code, "name": h["name"],
        "price": price, "shares": shares, "revenue": revenue, "date": date
    }
    data["trades"].append(trade)
    remaining = h["shares"] - shares
    if remaining <= 0:
        del data["holdings"][code]
    else:
        data["holdings"][code]["shares"] = remaining
    save(data)
    return trade


def get_portfolio_status(price_map=None):
    """获取当前持仓状态。price_map: {code: current_price}"""
    data = load()
    holdings = []
    total_value = data["cash"]
    total_cost = 0

    for code, h in data.get("holdings", {}).items():
        price = price_map.get(code) if price_map else None
        mv = price * h["shares"] if price else 0
        pnl = (price - h["avg_cost"]) * h["shares"] if price else 0
        pnl_pct = (price / h["avg_cost"] - 1) * 100 if price and h["avg_cost"] > 0 else 0
        total_value += mv
        total_cost += h["cost_basis"]
        holdings.append({
            "code": code, "name": h["name"],
            "shares": h["shares"], "avg_cost": h["avg_cost"],
            "price": price, "market_value": mv,
            "pnl": pnl, "pnl_pct": pnl_pct,
        })

    return {
        "cash": data["cash"],
        "holdings": holdings,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pnl": total_value - total_cost - data["cash"] + data["cash"],  # simplified
        "total_return": (total_value / (total_cost + data["cash"] - data.get("cash", 0)) - 1) * 100 if (total_cost + data["cash"]) > 0 else 0,
        "trades": data.get("trades", []),
    }
