#!/usr/bin/env python3
"""
持仓跟踪模块 v2 (核心-卫星三仓)
================================
统一账户文件 portfolio.json:
  {
    "cash": 100000,
    "trades": [],
    "holdings": {
      "600519": {"name":"贵州茅台","bucket":"anchor","cost":1500,
                 "shares":300,"high":1650,"industry":"白酒",
                 "date":"2026-03-01","notes":""}
    }
  }

相比 v1:
  - 每只持仓带 bucket(仓位归属) / shares(股数) / high(买入后最高价)
  - 体检委托 risk_engine: 三仓移动止损 + 敞口, 取代旧的"固定±20%一刀切"
  - total_equity() 用 cash + 持仓市值 实时算, 供权重计算
  - 保留 check_positions()/add_position() 等函数名, scanner 旧调用无需改动
  - 自动迁移旧 holdings.json(若存在)
"""
import json
import os
import sys

# 旧阈值保留仅为兼容(不再用于新体检; 新体检走 risk_engine 的三仓止损)
STOP_LOSS_PCT = -0.20
TAKE_PROFIT_PCT = 0.50

DEFAULT_PORTFOLIO = {"cash": 0.0, "trades": [], "holdings": {}}
_DEFAULT_BUCKET = "anchor"


def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def portfolio_path():
    return os.path.join(_app_dir(), "portfolio.json")


def _holdings_json_path():
    return os.path.join(_app_dir(), "holdings.json")


# ────────────────────── 读写 / 迁移 ──────────────────────

def load_portfolio():
    """读取账户。不存在则尝试从旧 holdings.json 迁移, 再退回默认。"""
    path = portfolio_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                p = json.load(f)
        except Exception:
            p = dict(DEFAULT_PORTFOLIO)
    else:
        p = _migrate_from_holdings_json()

    # 补全顶层键
    for k, v in DEFAULT_PORTFOLIO.items():
        p.setdefault(k, v if not isinstance(v, (list, dict)) else type(v)())
    # 补全每只持仓字段
    for code, h in p.get("holdings", {}).items():
        h.setdefault("name", "")
        h.setdefault("bucket", _DEFAULT_BUCKET)
        h.setdefault("cost", 0.0)
        h.setdefault("shares", 0)
        h.setdefault("high", h.get("cost", 0.0))
        h.setdefault("industry", "")
        h.setdefault("date", "")
        h.setdefault("notes", "")
    return p


def _migrate_from_holdings_json():
    """把旧 holdings.json({code:{name,cost,date,notes}}) 迁到新结构。"""
    p = dict(DEFAULT_PORTFOLIO)
    p["holdings"] = {}
    old_path = _holdings_json_path()
    if os.path.exists(old_path):
        try:
            with open(old_path, "r", encoding="utf-8") as f:
                old = json.load(f)
            for code, info in old.items():
                cost = info.get("cost", 0.0)
                p["holdings"][code] = {
                    "name": info.get("name", ""), "bucket": _DEFAULT_BUCKET,
                    "cost": cost, "shares": info.get("shares", 0),
                    "high": max(cost, info.get("high", cost)),
                    "industry": info.get("industry", ""),
                    "date": info.get("date", ""), "notes": info.get("notes", ""),
                }
        except Exception:
            pass
    return p


def save_portfolio(p):
    with open(portfolio_path(), "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


# 兼容旧名
def load_holdings():
    """兼容旧接口: 返回 holdings 字典部分。"""
    return load_portfolio().get("holdings", {})


def save_holdings(holdings):
    p = load_portfolio()
    p["holdings"] = holdings
    save_portfolio(p)


# ────────────────────── 持仓增删 ──────────────────────

def add_position(code, name, cost, date, bucket=_DEFAULT_BUCKET,
                 shares=0, high=None, industry="", notes=""):
    """添加/更新持仓。新增 bucket/shares/high 参数(有默认, 旧调用仍可用)。"""
    p = load_portfolio()
    p["holdings"][code] = {
        "name": name, "bucket": bucket, "cost": cost,
        "shares": shares, "high": high if high is not None else cost,
        "industry": industry, "date": date, "notes": notes,
    }
    save_portfolio(p)


def remove_position(code):
    p = load_portfolio()
    p["holdings"].pop(code, None)
    save_portfolio(p)


def update_highs(price_map):
    """维护移动止损基准: 现价创新高则抬高 high。返回更新只数。"""
    p = load_portfolio()
    changed = 0
    for code, h in p["holdings"].items():
        price = price_map.get(code)
        if price and price > (h.get("high") or 0):
            h["high"] = price
            changed += 1
    if changed:
        save_portfolio(p)
    return changed


# ────────────────────── 组合估值 ──────────────────────

def total_equity(price_map):
    """总资产 = 现金 + Σ持仓市值(有现价用现价, 否则用成本)。"""
    p = load_portfolio()
    equity = float(p.get("cash", 0) or 0)
    for code, h in p["holdings"].items():
        shares = h.get("shares", 0) or 0
        price = price_map.get(code) or h.get("cost", 0)
        equity += shares * price
    return equity


def to_positions(price_map):
    """把 holdings 转成 risk_engine 用的持仓列表。"""
    p = load_portfolio()
    out = []
    for code, h in p["holdings"].items():
        price = price_map.get(code)
        out.append({
            "code": code, "name": h.get("name", ""),
            "bucket": h.get("bucket", _DEFAULT_BUCKET),
            "cost": h.get("cost", 0.0), "shares": h.get("shares", 0),
            "price": price, "high": h.get("high") or h.get("cost", 0.0),
            "industry": h.get("industry", ""), "date": h.get("date", ""),
        })
    return out


# ────────────────────── 体检(委托 risk_engine, 兼容旧签名) ──────────────────────

def check_positions(price_map, code_name_map=None):
    """对持仓做体检。返回 (positions, alerts)。

    兼容旧调用: 返回的 positions 仍含 code/name/cost/price/pnl_pct/date/alerts,
    另外补充 bucket/shares/high/drawdown_pct/stop_price/dist_to_stop_pct。
    体检口径改为 risk_engine 三仓移动止损, 而非旧的固定±20%。
    """
    try:
        import risk_engine as re
        import portfolio_config as pc
        buckets = pc.load()
    except Exception:
        buckets = None

    positions_in = to_positions(price_map)
    if not positions_in:
        return [], []

    positions, alerts = [], []
    for pos in positions_in:
        pnl = None
        if pos["price"] and pos["cost"]:
            pnl = (pos["price"] - pos["cost"]) / pos["cost"] * 100
        row = {
            "code": pos["code"], "name": pos["name"], "bucket": pos["bucket"],
            "cost": pos["cost"], "shares": pos["shares"], "price": pos["price"],
            "high": pos["high"], "industry": pos["industry"],
            "date": pos["date"], "pnl_pct": pnl, "alerts": [],
        }
        if buckets:
            m = re.position_metrics(pos, buckets)
            row["drawdown_pct"] = m["drawdown_pct"]
            row["stop_price"] = m["stop_price"]
            row["dist_to_stop_pct"] = m["dist_to_stop_pct"]
            row["alerts"] = m["alerts"]
            for a in m["alerts"]:
                if a.startswith("⛔"):
                    alerts.append(f"{pos['code']} {pos['name']}: {a}")
        positions.append(row)
    return positions, alerts
