#!/usr/bin/env python3
"""
四策略筛选 — 一次扫描数据，四种策略视角
=====================================
价值稳健 / 红利收租 / 高管抄作业 / 困境反转
"""
from datetime import datetime


# ── 四策略定义 ──
STRATEGIES = {
    "value": {
        "name": "价值稳健",
        "icon": "V",
        "desc": "便宜好公司，长期持有",
        "filter": {
            "pe_min": 3, "pe_max": 40,
            "roe_min": 5,
            "mktcap_min": 50, "mktcap_max": 10000,
            "div_required": False,
            "insider_required": False,
            "turnaround": False,
        },
        "sort_by": "roe",
        "max_count": 15,
    },
    "dividend": {
        "name": "红利收租",
        "icon": "D",
        "desc": "高分红，买了吃息",
        "filter": {
            "pe_min": 3, "pe_max": 30,
            "roe_min": 5,
            "mktcap_min": 50, "mktcap_max": 10000,
            "div_yield_min": 1.5,
            "div_count_min": 3,
            "div_required": True,
            "insider_required": False,
            "turnaround": False,
        },
        "sort_by": "div_yield",
        "max_count": 10,
    },
    "insider": {
        "name": "高管抄作业",
        "icon": "I",
        "desc": "高管增持信号，跟内部人走",
        "filter": {
            "pe_min": 3, "pe_max": 200,
            "roe_min": 0,
            "mktcap_min": 20, "mktcap_max": 5000,
            "div_required": False,
            "insider_required": True,
            "turnaround": False,
        },
        "sort_by": "insider_positive",
        "max_count": 10,
    },
    "turnaround": {
        "name": "困境反转",
        "icon": "T",
        "desc": "烂到不能再烂，开始好转",
        "filter": {
            "pe_min": 3, "pe_max": 15,
            "roe_min": -5, "roe_max": 8,
            "mktcap_min": 20, "mktcap_max": 3000,
            "div_required": False,
            "insider_required": False,
            "turnaround": True,
        },
        "sort_by": "roe_improving",
        "max_count": 10,
    },
}


def apply_strategy_filters(candidates, dividend_data=None, insider_alerts=None):
    """对已过滤的全量候选池，按四种策略分别筛选。
    返回: {"value": [...], "dividend": [...], "insider": [...], "turnaround": [...]}
    """
    results = {}
    for key, cfg in STRATEGIES.items():
        f = cfg["filter"]
        pool = []

        for c in candidates:
            pe = c.get("pe")
            roe = c.get("roe")
            mv = c.get("mktcap")

            # 基础：PE/ROE/市值
            if pe is None or pe < f["pe_min"] or pe > f["pe_max"]:
                continue
            if roe is None or roe < f.get("roe_min", -100):
                continue
            if mv is not None:
                if mv < f["mktcap_min"] or mv > f["mktcap_max"]:
                    continue

            # 红利型：股息率+分红次数
            if f.get("div_required"):
                dy = c.get("div_yield")
                dc = c.get("div_count")
                if dy is None or dy < f.get("div_yield_min", 0):
                    continue
                if dc is None or dc < f.get("div_count_min", 0):
                    continue

            # 高管型：必须有增持信号(买入>卖出)
            if f.get("insider_required"):
                flag = c.get("insider_flag")
                if not flag:
                    continue
                # 只看增持（反向信号：高管增持=好）
                detail = c.get("insider_detail", "")
                # insider_flag: red=大量抛售, yellow=偏空
                # 我们想要的是增持信号 — 不在red/yellow里就是增持或平常
                if flag in ("red", "yellow"):
                    continue

            # 反转型：ROE低但必须为正且在改善中
            if f.get("turnaround"):
                if roe is None or roe > f.get("roe_max", 8):
                    continue
                # 至少ROE为正（已经从负转正）
                if roe < 0:
                    continue
                # 利润增长必须为正(改善迹象)
                pg = c.get("profit_growth")
                if pg is None or pg < 0:
                    continue

            c["strategy"] = key
            pool.append(c)

        # 排序
        sort_by = cfg["sort_by"]
        if sort_by == "roe":
            pool.sort(key=lambda x: x.get("roe") or 0, reverse=True)
        elif sort_by == "div_yield":
            pool.sort(key=lambda x: x.get("div_yield") or 0, reverse=True)
        elif sort_by == "roe_improving":
            pool.sort(key=lambda x: x.get("profit_growth") or 0, reverse=True)
        elif sort_by == "insider_positive":
            # 按ROE排，有高管信号的优先
            pool.sort(key=lambda x: (1 if c.get("insider_flag") else 0, x.get("roe") or 0), reverse=True)

        results[key] = pool[:cfg["max_count"]]

    return results


def build_strategy_report(all_results, macro_data=None):
    """生成四策略总览报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "=" * 64,
        f"  四策略扫描 — {now}",
        "=" * 64,
        "",
    ]

    for key in ("value", "dividend", "insider", "turnaround"):
        cfg = STRATEGIES[key]
        pool = all_results.get(key, [])
        lines.append(f"## {cfg['icon']} {cfg['name']} — {cfg['desc']}")
        lines.append(f"  {len(pool)} 只候选")
        if pool:
            lines.append("| 代码 | 名称 | PE | ROE% | 分红% | 市值(亿) | 行业 | 信号 |")
            lines.append("|------|------|-----|------|-------|---------|------|------|")
            for c in pool[:10]:
                pe = f"{c.get('pe',0):.1f}" if c.get('pe') else "-"
                roe = f"{c.get('roe',0):.1f}" if c.get('roe') else "-"
                dy = f"{c.get('div_yield'):.1f}" if c.get('div_yield') else "-"
                mv = f"{c.get('mktcap',0):.0f}" if c.get('mktcap') else "-"
                sig = c.get("insider_detail", "")[:12] if c.get("insider_detail") else "-"
                lines.append(f"| {c.get('code')} | {c.get('name')} | {pe} | {roe} | {dy} | {mv} | {c.get('industry','')} | {sig} |")
        lines.append("")
        lines.append("")

    return "\n".join(lines)


def strategy_buy_sell_rules():
    """各策略的买卖规则（纯文本）"""
    return """
## 投资策略手册

### V 价值稳健
- **买**: PE 3-20区间分3批建仓，每跌5%加一笔
- **持有**: 1-3年，季度检查ROE是否>5%、PE是否<60
- **卖**: ROE连续两季<5% / PE>60 / 扣非ROE<3%
- **仓位**: 单只≤20%，总仓位≤60%

### D 红利收租
- **买**: 股息率>4%时分批买入，不追涨
- **持有**: 长期不卖，吃分红
- **卖**: 分红中断 / 股息率稀释到<2% / ROE<3%
- **仓位**: 单只≤15%，红利组合合计≤30%

### I 高管抄作业
- **买**: 高管增持公告后3日内买入，不追高
- **持有**: 6个月，或高管再次增持延长
- **卖**: 高管开始减持 / 6个月到 / -10%止损
- **仓位**: 单只≤5%，信号组合合计≤15%

### T 困境反转
- **买**: ROE转正后首次回踩均线时分2批买
- **持有**: 季度验证ROE是否持续改善
- **卖**: ROE再次转负 / -15%硬止损 / 利润增速<0
- **仓位**: 单只≤3%，反转组合合计≤10%
"""
