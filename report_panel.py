#!/usr/bin/env python3
"""
周报风控面板
============
把风控引擎的输出渲染成报告用的 Markdown 段落:
  · 三仓敞口(目标 vs 实际 vs 余量)
  · 持仓体检(盈亏 / 回撤 / 距止损 / 告警)
  · 最坏情形假设(卫星全灭 + 动量全止损)
  · 集中度提示
纯字符串拼接, 可测。
"""
from __future__ import annotations
import risk_engine as re


def build_risk_panel(positions, equity, buckets_cfg) -> str:
    r = []
    r.append("## 风控面板\n")

    # ── 三仓敞口 ──
    exp = re.bucket_exposure(positions, equity, buckets_cfg)
    r.append("### 三仓敞口\n")
    r.append("| 仓位 | 实际 | 目标 | 上限 | 余量 | 状态 |")
    r.append("|------|------|------|------|------|------|")
    for key in ("anchor", "momentum", "satellite"):
        e = exp.get(key)
        if not e:
            continue
        status = "🔴超限" if e["over"] else "🟢"
        r.append(f"| {e['name']} | {e['weight']:.1%} | {e['target']:.0%} | "
                 f"{e['max']:.0%} | {e['room_w']:.1%} | {status} |")
    cash = exp["_cash"]
    r.append(f"| {cash['name']} | {cash['weight']:.1%} | - | - | - | - |")

    # ── 最坏情形假设 ──
    ml = re.max_loss_assumption(positions, equity, buckets_cfg)
    r.append("\n### 最坏情形假设(非预测, 帮助 sizing 直觉)\n")
    r.append(f"- 卫星全灭(归零): **-{ml['satellite_wipeout_pct']:.1f}%**")
    r.append(f"- 动量全打止损: **-{ml['momentum_allstop_pct']:.1f}%**")
    r.append(f"- 合计(压舱仓不计): **-{ml['combined_pct']:.1f}%**")

    # ── 集中度 ──
    nw, nc, iw, ic = re.concentration(positions, equity)
    if nc:
        r.append("\n### 集中度\n")
        r.append(f"- 最大单票: {nc} {nw:.1%}" +
                 ("  ⚠️ 单票偏重" if nw > 0.10 else ""))
        if ic:
            r.append(f"- 最大行业: {ic} {iw:.1%}" +
                     ("  ⚠️ 行业偏重" if iw > 0.30 else ""))

    # ── 持仓体检 ──
    r.append("\n### 持仓体检\n")
    if not positions:
        r.append("(无持仓)")
        return "\n".join(r)
    r.append("| 代码 | 名称 | 仓 | 盈亏 | 距成本高点 | 止损价 | 距止损 | 告警 |")
    r.append("|------|------|----|------|-----------|--------|--------|------|")
    for p in positions:
        m = re.position_metrics(p, buckets_cfg)
        bname = buckets_cfg.get(p.get("bucket"), {}).get("name", p.get("bucket", "-"))
        pnl = f"{m['pnl_pct']:+.1f}%" if m["pnl_pct"] is not None else "-"
        dd = f"{m['drawdown_pct']:+.1f}%" if m["drawdown_pct"] is not None else "-"
        sp = f"{m['stop_price']:.2f}" if m["stop_price"] is not None else "-"
        dts = f"{m['dist_to_stop_pct']:+.1f}%" if m["dist_to_stop_pct"] is not None else "-"
        alerts = "; ".join(a for a in m["alerts"] if a.startswith(("⛔", "⚠️"))) or "-"
        r.append(f"| {p.get('code')} | {p.get('name')} | {bname} | {pnl} | {dd} | "
                 f"{sp} | {dts} | {alerts} |")

    # 触发止损汇总
    hits = re.scan_stops(positions, buckets_cfg)
    if hits:
        r.append("\n**⛔ 止损提示:**")
        for code, name, alert in hits:
            r.append(f"- {code} {name}: {alert}")

    return "\n".join(r)
