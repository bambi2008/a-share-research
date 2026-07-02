#!/usr/bin/env python3
"""
投资记录本 v2 — 记录买卖、计算盈亏、追踪总资产、三仓归属
存储: portfolio.json（与 exe 同目录）

相比 v1:
  - 每只持仓可带 bucket(仓位归属: anchor/momentum/satellite) 与 high(买入后最高价)
  - 完全向后兼容: 旧持仓自动归入压舱仓 anchor, high 默认成本价
  - 修正 v1 get_portfolio_status 里 total_pnl / total_return 的笔误
  - 新增 to_risk_positions()/total_equity()/update_highs()/set_bucket() 供风控引擎使用
"""
import json, os, sys
from datetime import datetime

_DEFAULT_BUCKET = "anchor"


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
        data = json.load(f)
    for code, h in data.get("holdings", {}).items():
        h.setdefault("bucket", _DEFAULT_BUCKET)
        h.setdefault("high", h.get("avg_cost", 0))
    data.setdefault("cash", 0)
    data.setdefault("trades", [])
    data.setdefault("holdings", {})
    return data

def save(data):
    with open(_path(), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def buy(code, name, price, shares, date=None, bucket=_DEFAULT_BUCKET):
    """买入记录。新增 bucket 参数（默认压舱仓），旧调用无需改动。"""
    data = load()
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    cost = price * shares
    data["cash"] -= cost
    trade = {
        "type": "buy", "code": code, "name": name,
        "price": price, "shares": shares, "cost": cost,
        "date": date, "bucket": bucket
    }
    data["trades"].append(trade)
    h = data["holdings"].get(code, {"shares": 0, "cost_basis": 0, "name": name,
                                    "bucket": bucket, "high": price})
    total_cost = h["cost_basis"] + cost
    total_shares = h["shares"] + shares
    data["holdings"][code] = {
        "shares": total_shares, "cost_basis": total_cost,
        "avg_cost": total_cost / total_shares if total_shares > 0 else 0,
        "name": name,
        "bucket": h.get("bucket", bucket),
        "high": max(h.get("high", 0), price),
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


def set_bucket(code, bucket):
    """调整某只持仓的仓位归属。"""
    data = load()
    if code in data["holdings"]:
        data["holdings"][code]["bucket"] = bucket
        save(data)
        return True
    return False


def update_highs(price_map):
    """维护移动止损基准: 现价创新高则抬高 high。返回更新只数。"""
    data = load()
    changed = 0
    for code, h in data["holdings"].items():
        price = price_map.get(code) if price_map else None
        if price and price > (h.get("high") or 0):
            h["high"] = price
            changed += 1
    if changed:
        save(data)
    return changed


def get_portfolio_status(price_map=None):
    """获取当前持仓状态。price_map: {code: current_price}"""
    data = load()
    holdings = []
    total_value = data["cash"]
    total_cost_basis = 0

    for code, h in data.get("holdings", {}).items():
        price = price_map.get(code) if price_map else None
        mv = price * h["shares"] if price else 0
        pnl = (price - h["avg_cost"]) * h["shares"] if price else 0
        pnl_pct = (price / h["avg_cost"] - 1) * 100 if price and h["avg_cost"] > 0 else 0
        total_value += mv
        total_cost_basis += h["cost_basis"]
        holdings.append({
            "code": code, "name": h["name"],
            "shares": h["shares"], "avg_cost": h["avg_cost"],
            "price": price, "market_value": mv,
            "pnl": pnl, "pnl_pct": pnl_pct,
            "bucket": h.get("bucket", _DEFAULT_BUCKET),
            "high": h.get("high", h["avg_cost"]),
        })

    invested_value = total_value - data["cash"]
    total_pnl = invested_value - total_cost_basis
    total_return = (total_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0

    return {
        "cash": data["cash"],
        "holdings": holdings,
        "total_value": total_value,
        "total_cost": total_cost_basis,
        "total_pnl": total_pnl,
        "total_return": total_return,
        "trades": data.get("trades", []),
    }


# ── 三仓视图（供风控引擎/GUI 用） ──

def to_risk_positions(price_map=None):
    """把 holdings 转成 risk_engine 用的持仓列表。"""
    data = load()
    out = []
    for code, h in data.get("holdings", {}).items():
        price = price_map.get(code) if price_map else None
        out.append({
            "code": code, "name": h.get("name", ""),
            "bucket": h.get("bucket", _DEFAULT_BUCKET),
            "cost": h.get("avg_cost", 0), "shares": h.get("shares", 0),
            "price": price, "high": h.get("high") or h.get("avg_cost", 0),
        })
    return out


def total_equity(price_map=None):
    """总资产 = 现金 + Σ持仓市值（有现价用现价，否则用成本）。"""
    data = load()
    eq = float(data.get("cash", 0) or 0)
    for code, h in data.get("holdings", {}).items():
        price = (price_map.get(code) if price_map else None) or h.get("avg_cost", 0)
        eq += price * h.get("shares", 0)
    return eq
