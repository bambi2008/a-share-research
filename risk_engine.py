#!/usr/bin/env python3
"""
风控引擎
========
核心-卫星杠铃的纪律执行层。全部为纯函数, 不触网, 可单测。

三个职责:
  1. 配仓守门 check_buy() —— 买入前拦截会突破 仓位上限 / 单票上限 的交易。
  2. 持仓体检 position_metrics() / scan_stops() —— 盈亏、回撤、距止损、触发止损。
  3. 组合视图 bucket_exposure() / concentration() / max_loss_assumption()。

持仓 dict 约定字段:
  code, name, bucket, cost(成本价), shares(股数), price(现价),
  high(买入后最高价, 用于移动止损; 缺省用 max(cost,price)),
  industry(可选)
"""
from __future__ import annotations


def market_value(pos) -> float:
    return (pos.get("price") or 0.0) * (pos.get("shares") or 0.0)


def _weight(mv: float, equity: float) -> float:
    return mv / equity if equity > 0 else 0.0


# ────────────────────── 配仓守门 ──────────────────────

def check_buy(positions, equity, bucket, code, buy_mv, buckets_cfg):
    """买入前守门。返回 (ok: bool, reasons: list[str])。

    拦截条件:
      · bucket 非法
      · 买入后该仓权重 > 仓位上限 max
      · 买入后该票(同仓)权重 > 单票上限 per_name_max
      · equity<=0 无法计算
    """
    reasons = []
    if bucket not in buckets_cfg:
        return False, [f"未知仓位: {bucket}"]
    if equity <= 0:
        return False, ["总资产为 0, 无法配仓"]
    if buy_mv <= 0:
        return False, ["买入金额需为正"]

    cfg = buckets_cfg[bucket]

    cur_bucket_mv = sum(market_value(p) for p in positions if p.get("bucket") == bucket)
    new_bucket_w = _weight(cur_bucket_mv + buy_mv, equity)
    if new_bucket_w > cfg["max"] + 1e-9:
        reasons.append(
            f"{cfg['name']}买入后权重 {new_bucket_w:.1%} > 上限 {cfg['max']:.0%}")

    cur_name_mv = sum(market_value(p) for p in positions
                      if p.get("bucket") == bucket and p.get("code") == code)
    new_name_w = _weight(cur_name_mv + buy_mv, equity)
    if new_name_w > cfg["per_name_max"] + 1e-9:
        reasons.append(
            f"{code} 买入后权重 {new_name_w:.1%} > 单票上限 {cfg['per_name_max']:.0%}")

    return (len(reasons) == 0), reasons


def room_to_buy(positions, equity, bucket, code, buckets_cfg):
    """还能买多少(金额, 取仓位余量与单票余量的较小值, ≥0)。"""
    if bucket not in buckets_cfg or equity <= 0:
        return 0.0
    cfg = buckets_cfg[bucket]
    cur_bucket_mv = sum(market_value(p) for p in positions if p.get("bucket") == bucket)
    cur_name_mv = sum(market_value(p) for p in positions
                      if p.get("bucket") == bucket and p.get("code") == code)
    bucket_room = cfg["max"] * equity - cur_bucket_mv
    name_room = cfg["per_name_max"] * equity - cur_name_mv
    return max(0.0, min(bucket_room, name_room))


# ────────────────────── 持仓体检 ──────────────────────

def position_metrics(pos, buckets_cfg):
    """单只持仓体检。返回 dict: pnl_pct, drawdown_pct, stop_price, dist_to_stop_pct, alerts。

    - pnl_pct        : 相对成本的盈亏
    - drawdown_pct   : 相对"买入后最高价"的回撤(移动止损口径)
    - stop_price     : 机械止损触发价(None=该仓不设机械止损)
    - dist_to_stop_pct: 现价距止损价还有多少(正=尚安全, 负=已破)
    """
    cost = pos.get("cost") or 0.0
    price = pos.get("price")
    bucket = pos.get("bucket")
    cfg = buckets_cfg.get(bucket, {})
    out = {"pnl_pct": None, "drawdown_pct": None,
           "stop_price": None, "dist_to_stop_pct": None, "alerts": []}

    if not price:
        out["alerts"].append("无现价, 数据缺失")
        return out

    if cost > 0:
        out["pnl_pct"] = (price - cost) / cost * 100

    high = pos.get("high") or max(cost, price)
    if high > 0:
        out["drawdown_pct"] = (price - high) / high * 100

    stop = cfg.get("stop")
    if stop is not None:
        # 移动止损参考最高价, 固定止损参考成本价
        ref = high if cfg.get("trailing") else cost
        if ref > 0:
            stop_price = ref * (1 + stop)
            out["stop_price"] = stop_price
            out["dist_to_stop_pct"] = (price - stop_price) / price * 100
            if price <= stop_price:
                out["alerts"].append(
                    f"⛔ 触发止损(现价{price:.2f} ≤ 止损{stop_price:.2f}), 应减仓")
            elif out["dist_to_stop_pct"] is not None and out["dist_to_stop_pct"] < 3:
                out["alerts"].append(
                    f"⚠️ 逼近止损(距止损 {out['dist_to_stop_pct']:.1f}%)")

    if cfg.get("speculative"):
        out["alerts"].append("🎲 卫星投机仓: 视作可归零的钱, 严格限仓")

    return out


def scan_stops(positions, buckets_cfg):
    """扫描所有持仓, 返回触发/逼近止损的清单 [(code, name, alert), ...]。"""
    hits = []
    for p in positions:
        m = position_metrics(p, buckets_cfg)
        for a in m["alerts"]:
            if a.startswith("⛔") or a.startswith("⚠️"):
                hits.append((p.get("code"), p.get("name"), a))
    return hits


# ────────────────────── 组合视图 ──────────────────────

def bucket_exposure(positions, equity, buckets_cfg):
    """各仓敞口。返回 {bucket: {mv, weight, target, max, room_w}} + 现金。"""
    out = {}
    invested = 0.0
    for key, cfg in buckets_cfg.items():
        mv = sum(market_value(p) for p in positions if p.get("bucket") == key)
        invested += mv
        w = _weight(mv, equity)
        out[key] = {
            "name": cfg["name"], "mv": mv, "weight": w,
            "target": cfg["target"], "max": cfg["max"],
            "room_w": max(0.0, cfg["max"] - w),
            "over": w > cfg["max"] + 1e-9,
        }
    out["_cash"] = {"name": "现金", "mv": max(0.0, equity - invested),
                    "weight": _weight(max(0.0, equity - invested), equity)}
    return out


def concentration(positions, equity):
    """集中度: 返回 (最大单票权重, 该票code, 最大行业权重, 该行业)。"""
    if equity <= 0 or not positions:
        return 0.0, None, 0.0, None
    by_name, by_ind = {}, {}
    for p in positions:
        mv = market_value(p)
        by_name[p.get("code")] = by_name.get(p.get("code"), 0.0) + mv
        ind = p.get("industry")
        if ind:
            by_ind[ind] = by_ind.get(ind, 0.0) + mv
    top_name, top_name_mv = max(by_name.items(), key=lambda x: x[1])
    if by_ind:
        top_ind, top_ind_mv = max(by_ind.items(), key=lambda x: x[1])
    else:
        top_ind, top_ind_mv = None, 0.0
    return (_weight(top_name_mv, equity), top_name,
            _weight(top_ind_mv, equity), top_ind)


def max_loss_assumption(positions, equity, buckets_cfg):
    """最坏情形假设(帮助 sizing 直觉, 非预测):
      - 卫星全灭     = 卫星仓当前权重(卫星不设止损, 假设归零)
      - 动量全止损   = 动量仓权重 × |止损线|
      - 合计         = 两者之和(压舱仓不计入, 视为相对稳定)
    返回 dict。
    """
    exp = bucket_exposure(positions, equity, buckets_cfg)
    sat_w = exp.get("satellite", {}).get("weight", 0.0)
    mom_w = exp.get("momentum", {}).get("weight", 0.0)
    mom_stop = abs(buckets_cfg.get("momentum", {}).get("stop") or 0.0)
    sat_loss = sat_w                      # 归零
    mom_loss = mom_w * mom_stop           # 全部打到止损
    return {
        "satellite_wipeout_pct": sat_loss * 100,
        "momentum_allstop_pct": mom_loss * 100,
        "combined_pct": (sat_loss + mom_loss) * 100,
    }
