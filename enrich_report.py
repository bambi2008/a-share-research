#!/usr/bin/env python3
"""
报告扩展层
==========
把三块新能力合成一段 Markdown, 追加到 scanner 周报尾部:
  A. 动量排名(A 动量弹性仓候选) —— 对本周候选池按动量打分排序
  B. 卫星凸性(B 高凸卫星仓候选) —— 高营收增速+中小盘+主题, 强制投机标记
  C. 风控面板              —— 三仓敞口 / 回撤 / 距止损 / 最坏情形

scanner 只需一处调用:
    import enrich_report
    report += "\n\n" + enrich_report.build_extension(candidates, price_map)

各块独立 try/except: 单块失败(如动量取数超时)不影响其余部分和主报告。
依赖可注入, 便于离线单测。
"""
from __future__ import annotations


def _fmt_pct(x, digits=1):
    return f"{x*100:+.{digits}f}%" if isinstance(x, (int, float)) else "-"


def build_momentum_section(candidates, price_map, data_source_mod=None,
                           momentum_mod=None, top_n=15):
    if momentum_mod is None:
        import momentum as momentum_mod
    if data_source_mod is None:
        import data_source as data_source_mod

    codes = [str(c["code"]) for c in candidates if c.get("code")]
    if not codes:
        return "## 动量排名(动量弹性仓候选)\n\n(本周无候选)"

    hist, meta = data_source_mod.get_price_history(codes, days=120)
    ranked = momentum_mod.rank_momentum(hist)[:top_n]

    r = ["## 动量排名(动量弹性仓候选)\n",
         f"> 数据: {meta} | 按 20/60日收益 + 均线 复合动量分排序\n"]
    if not ranked:
        r.append("(历史数据不足, 无法计算动量; 稍后重试或检查数据源)")
        return "\n".join(r)

    name_map = {str(c["code"]): c.get("name", "") for c in candidates}
    r.append("| 排名 | 代码 | 名称 | 动量分 | 20日 | 60日 | 站上MA20 | 站上MA60 |")
    r.append("|------|------|------|--------|------|------|---------|---------|")
    for i, row in enumerate(ranked, 1):
        code = row["code"]
        r.append(
            f"| {i} | {code} | {name_map.get(code,'')} | {row['score']:+.3f} | "
            f"{_fmt_pct(row.get('ret20'))} | {_fmt_pct(row.get('ret60'))} | "
            f"{'✓' if row.get('above_ma20') else '·'} | "
            f"{'✓' if row.get('above_ma60') else '·'} |")
    return "\n".join(r)


def build_satellite_section(candidates, satellite_mod=None, top_n=5):
    if satellite_mod is None:
        import satellite as satellite_mod
    picks, notes = satellite_mod.screen_satellite(candidates, max_names=top_n)

    r = ["## 高凸卫星仓候选\n"]
    for n in notes:
        r.append(f"> {n}")
    r.append("")
    if picks:
        r.append("| 代码 | 名称 | 行业 | 营收增% | 利润增% | 流通市值(亿) | 限仓 |")
        r.append("|------|------|------|---------|---------|------|------|")
        for c in picks:
            rev = f"{c['rev_growth']:.0f}" if c.get("rev_growth") is not None else "-"
            prof = f"{c['profit_growth']:.0f}" if c.get("profit_growth") is not None else "-"
            mv = f"{c['mktcap']:.0f}" if c.get("mktcap") is not None else "-"
            r.append(f"| {c['code']} | {c.get('name','')} | {c.get('industry','')} | "
                     f"{rev} | {prof} | {mv} | {c.get('per_name_cap_note','')} |")
    return "\n".join(r)


def build_risk_section(price_map, position_mod=None, config_mod=None,
                       panel_mod=None):
    """持仓来源优先用 GUI 的 portfolio 模块; 若不可用再退回 position 模块。

    portfolio.to_risk_positions()/total_equity() 与 position 的同名接口签名一致,
    因此二者可互换。
    """
    if config_mod is None:
        import portfolio_config as config_mod
    if panel_mod is None:
        import report_panel as panel_mod

    positions, equity = None, None
    if position_mod is not None:
        # 显式注入(测试用)
        try: position_mod.update_highs(price_map)
        except Exception: pass
        positions = position_mod.to_risk_positions(price_map) \
            if hasattr(position_mod, "to_risk_positions") \
            else position_mod.to_positions(price_map)
        equity = position_mod.total_equity(price_map)
    else:
        # 默认: 先试 portfolio(GUI 用), 再退 position
        for mod_name, pos_fn in (("portfolio", "to_risk_positions"),
                                 ("position", "to_positions")):
            try:
                mod = __import__(mod_name)
                try: mod.update_highs(price_map)
                except Exception: pass
                positions = getattr(mod, pos_fn)(price_map)
                equity = mod.total_equity(price_map)
                break
            except Exception:
                continue

    if positions is None:
        positions, equity = [], 0
    buckets = config_mod.load()
    return panel_mod.build_risk_panel(positions, equity, buckets)


def build_extension(candidates, price_map, data_source_mod=None,
                    momentum_mod=None, satellite_mod=None,
                    position_mod=None, config_mod=None, panel_mod=None):
    """合成报告扩展段。各块独立容错。"""
    parts = []

    try:
        parts.append(build_satellite_section(candidates, satellite_mod))
    except Exception as e:
        parts.append(f"## 高凸卫星仓候选\n\n⚠️ 生成失败: {e}")

    try:
        parts.append(build_momentum_section(candidates, price_map,
                                            data_source_mod, momentum_mod))
    except Exception as e:
        parts.append(f"## 动量排名(动量弹性仓候选)\n\n⚠️ 生成失败: {e}")

    try:
        parts.append(build_risk_section(price_map, position_mod, config_mod, panel_mod))
    except Exception as e:
        parts.append(f"## 风控面板\n\n⚠️ 生成失败: {e}")

    return "\n\n".join(parts)
