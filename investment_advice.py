#!/usr/bin/env python3
"""
投资建议模块 — 基于扫描结果 + LLM 研判，输出具体买卖建议
"""
from datetime import datetime


def build_advice_prompt(candidates, growth_mode=False, scan_summary=""):
    """构造投资建议 prompt"""
    lines = [
        "你是一名资深 A 股投资顾问，客户是个人投资者（验证仓资金 5-10 万）。",
        "请基于以下候选池，给出具体的投资建议。",
        "",
        f"## 候选池概览",
        f"模式: {'成长股(营收增长优先)' if growth_mode else '价值股(ROE优先)'}",
        f"候选数: {len(candidates)} 只",
        f"{scan_summary}",
        "",
        "## 候选公司数据 (前15只)",
        "| 代码 | 名称 | PE | ROE% | 扣非ROE% | 价格 | 市值(亿) | 行业 | 营收增% | 利润增% |",
        "|------|------|-----|------|---------|------|---------|------|---------|---------|",
    ]

    for c in candidates[:15]:
        pe = f"{c.get('pe',0):.1f}" if c.get('pe') else "-"
        roe = f"{c.get('roe',0):.1f}" if c.get('roe') is not None else "-"
        droe = f"{c.get('deduct_roe',0):.1f}" if c.get('deduct_roe') is not None else "-"
        price = f"{c.get('price',0):.2f}" if c.get('price') else "-"
        mv = f"{c.get('mktcap',0):.0f}" if c.get('mktcap') else "-"
        rev = f"{c.get('rev_growth',0):.1f}" if c.get('rev_growth') is not None else "-"
        prof = f"{c.get('profit_growth',0):.1f}" if c.get('profit_growth') is not None else "-"
        lines.append(f"| {c.get('code','')} | {c.get('name','')} | {pe} | {roe} | {droe} | {price} | {mv} | {c.get('industry','')} | {rev} | {prof} |")

    lines.extend([
        "",
        "## 分析要求",
        "",
        "请输出以下结构化的投资建议（务实、具体、可执行）：",
        "",
        "**一、核心判断**: 当前市场环境下该板块的整体策略（积极/谨慎/观望），一句话逻辑",
        "",
        "**二、推荐买入（3-5只）**: 表格形式，每只含：",
        "  - 代码、名称、推荐仓位(%)",
        "  - 买入价格区间（基于当前价给合理区间，不要低于现价50%以上揣测）",
        "  - 止损价、止盈价",
        "  - 一句话推荐逻辑（必须结合具体数据：如扣非ROE高/营收增长加速/行业供需紧张）",
        "  - 如果某只利润同比暴增>300%，标注⚠️周期顶部风险",
        "",
        "**三、建议回避**: 1-2只候选池里看起来好但实际有问题的（如周期顶部、扣非ROE远低于ROE、ST股）",
        "",
        "**四、仓位分配**: 总资金5-10万，每只不超过20%，保留现金比例",
        "",
        "**五、操作日历**: 未来1-3个月的关键观察节点（如Q2财报披露、政策窗口、行业催化剂）",
        "",
        "**六、风险提示**: 最核心的2-3个下行风险",
        "",
        "注意:",
        "- 价格区间要合理，基于当前价格给5-15%的浮动范围",
        "- 必须区分成长股和价值股，给出不同的买卖逻辑",
        "- 如果候选池中某公司扣非ROE为'-'或远低于ROE，必须指出",
        "- 不要推荐ST股",
        "- 仓位分配要加起来=100%",
    ])
    return "\n".join(lines)


def generate_advice(scan_result, growth_mode, llm_chat_fn, progress_callback=None):
    """
    生成投资建议。
    scan_result: scanner.run_scan 的返回值
    growth_mode: 是否成长股模式
    llm_chat_fn: messages → response 的 LLM 调用函数
    """
    def log(m):
        if progress_callback: progress_callback(m)

    cands = scan_result.get("candidates_full") or []
    if not cands:
        return "⚠️ 无候选数据，请先扫描"

    summary = f"覆盖{scan_result.get('industry_count',0)}行业, {scan_result.get('total_stocks',0)}只股票"

    log("生成投资建议...")
    prompt = build_advice_prompt(cands, growth_mode, summary)

    analysis = llm_chat_fn([
        {"role": "user", "content": prompt}
    ], temperature=0.4, max_tokens=2000)

    # 组装报告
    report = []
    report.append("=" * 64)
    report.append("  💰 投资建议 — AI 投资顾问研判")
    report.append(f"  生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"  模式: {'成长股' if growth_mode else '价值股'}")
    report.append("=" * 64)
    report.append("")
    report.append(analysis)
    report.append(f"\n\n---")
    report.append("*本建议由 AI 基于公开数据生成，仅供研究参考，不构成投资建议。*")
    report.append("*建议用小资金验证，逐步调整策略。*")
    return "\n".join(report)
