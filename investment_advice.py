#!/usr/bin/env python3
"""
投资建议模块 v2 — 硬规则(仓位/止损) + LLM(仅定性)
====================================================
相比 v1 的关键改变:
  - 仓位%、止损价 由 risk_engine/portfolio_config 的三仓规则计算(可复现、可验证),
    不再让 LLM 凭空报点位。
  - LLM 只负责"定性": 推荐逻辑、催化剂、风险因素、回避理由、操作节点。
  - 删除 v1 让 LLM 编造的"6月预测XX元/12-18月触及XX元"——语言模型无预测效力,
    报点位等于话术, 会误导下注。
  - 明确标注: AI 定性参考, 非投资建议。
"""
from datetime import datetime


def _bucket_of(candidate, growth_mode, boom_mode):
    """按候选特征归入三仓（与 satellite/momentum 口径一致的粗判）。"""
    if boom_mode:
        return "satellite"
    rev = candidate.get("rev_growth") or 0
    mv = candidate.get("mktcap") or 0
    # 高增速中小盘 → 动量弹性; 其余 → 压舱
    if growth_mode and rev >= 30 and 30 <= mv <= 300:
        return "momentum"
    return "anchor"


def compute_rule_based_plan(candidates, growth_mode=False, boom_mode=False,
                            equity=None, buckets_cfg=None, top_n=8):
    """用硬规则算出每只候选的: 仓位上限% / 止损价 / 止损距离。

    返回 [{code,name,bucket,price,per_name_cap_pct,max_buy_amount,
           stop_price,stop_pct,note}, ...]
    """
    try:
        import portfolio_config
        buckets_cfg = buckets_cfg or portfolio_config.load()
    except Exception:
        # 兜底默认（与 portfolio_config.DEFAULT_BUCKETS 对齐）
        buckets_cfg = {
            "anchor":    {"name": "压舱仓", "per_name_max": 0.10, "stop": None,  "trailing": False},
            "momentum":  {"name": "动量弹性仓", "per_name_max": 0.07, "stop": -0.10, "trailing": True},
            "satellite": {"name": "高凸卫星仓", "per_name_max": 0.03, "stop": None,  "trailing": False},
        }

    plans = []
    for c in candidates[:top_n]:
        bucket = _bucket_of(c, growth_mode, boom_mode)
        cfg = buckets_cfg.get(bucket, {})
        price = c.get("price")
        cap_pct = cfg.get("per_name_max", 0.05)
        plan = {
            "code": c.get("code", ""), "name": c.get("name", ""),
            "bucket": bucket, "bucket_name": cfg.get("name", bucket),
            "price": price,
            "per_name_cap_pct": cap_pct * 100,
            "max_buy_amount": (equity * cap_pct) if equity else None,
            "stop_price": None, "stop_pct": None,
            "note": "",
        }
        stop = cfg.get("stop")
        if stop is not None and price:
            # 建仓时移动止损基准=现价, 故止损价 = 现价×(1+stop)
            plan["stop_price"] = price * (1 + stop)
            plan["stop_pct"] = abs(stop) * 100
        if bucket == "satellite":
            plan["note"] = "投机仓·可归零的钱·不设机械止损靠限仓控制"
        plans.append(plan)
    return plans


def build_qualitative_prompt(candidates, plans, growth_mode=False, scan_summary="", data_period="2026年Q1"):
    """LLM 只做定性: 推荐逻辑/催化剂/风险/回避。不让它报任何价格点位。"""
    from datetime import datetime
    today = datetime.now().strftime('%Y年%m月%d日')
    lines = [
        "你是一名严谨的 A 股研究员。下面给你候选池数据，以及系统已按风控规则算好的仓位与止损。",
        f"今天是 {today}，财务数据截止 {data_period}（最新一期季报）。",
        "你的任务【仅限定性分析】——绝对不要给出任何买入价、目标价、止盈价或未来价格预测。",
        "价格与仓位由系统规则负责，你只负责判断逻辑、催化剂与风险。",
        "",
        "【重要】营收增%、利润增% 是同比数据。你分析的是最新财报(Q1 2026)，",
        "不要提任何过去的年份(2024/2025)，不要说'根据2024年/2025年数据'。",
        "只说'最新财报显示'、'Q1表现'即可。绝对不要输出包含2024或2025年份的句子。",
        "",
        f"模式: {'成长股(营收增长优先)' if growth_mode else '价值股(ROE优先)'} | {scan_summary}",
        "",
        "## 候选数据",
        "| 代码 | 名称 | PE | ROE% | 扣非ROE% | 市值(亿) | 行业 | 概念板块 | 营收增% | 利润增% |",
        "|------|------|-----|------|---------|---------|------|---------|---------|---------|",
    ]
    for c in candidates[:20]:
        pe = f"{c.get('pe',0):.1f}" if c.get('pe') else "-"
        roe = f"{c.get('roe',0):.1f}" if c.get('roe') is not None else "-"
        droe = f"{c.get('deduct_roe',0):.1f}" if c.get('deduct_roe') is not None else "-"
        mv = f"{c.get('mktcap',0):.0f}" if c.get('mktcap') else "-"
        rev = f"{c.get('rev_growth',0):.1f}" if c.get('rev_growth') is not None else "-"
        prof = f"{c.get('profit_growth',0):.1f}" if c.get('profit_growth') is not None else "-"
        concepts_str = "/".join(c.get('concepts', [])) if c.get('concepts') else "-"
        lines.append(f"| {c.get('code','')} | {c.get('name','')} | {pe} | {roe} | {droe} | {mv} | {c.get('industry','')} | {concepts_str} | {rev} | {prof} |")

    lines.extend([
        "",
        "## 输出要求（纯文本，【一、】做大标题，· 做条目）",
        "",
        "【一、板块判断】当前该板块整体处境（积极/谨慎/观望）+ 一句话逻辑",
        "",
        "【二、候选点评】对前几只逐一给出（不涉及价格）:",
        "  · 代码 名称 → 推荐/中性/回避 → 一句话逻辑(结合ROE/增速/扣非差异) → 关键催化剂 → 主要风险",
        "",
        "【三、需要警惕的】扣非ROE远低于ROE、疑似周期顶部、ST 等问题标的，点名并说明原因",
        "",
        "【四、观察节点】未来1-3个月值得跟踪的事件（财报/政策/行业催化）",
        "",
        "【五、核心风险】最重要的 2-3 个下行风险",
        "",
        "再次强调: 不要输出任何价格数字、目标价、止盈止损价——那些系统已按规则算好。",
    ])
    return "\n".join(lines)


def _fmt_plan_table(plans):
    """把硬规则计划渲染成表格文本（这些是可复现的真数字）。"""
    r = ["【系统风控计划（规则计算，非预测）】",
         "代码     仓位归属   单票上限   参考现价   移动止损价   止损幅度   可买上限"]
    for p in plans:
        price = f"{p['price']:.2f}" if p.get("price") else "-"
        stop = f"{p['stop_price']:.2f}" if p.get("stop_price") else "—(靠限仓)"
        stop_pct = f"-{p['stop_pct']:.0f}%" if p.get("stop_pct") else "—"
        cap_amt = f"{p['max_buy_amount']:,.0f}元" if p.get("max_buy_amount") else f"{p['per_name_cap_pct']:.0f}%"
        r.append(f"{p['code']:<8} {p['bucket_name']:<8} "
                 f"{p['per_name_cap_pct']:.0f}%{'':<6} {price:<9} {stop:<11} {stop_pct:<8} {cap_amt}")
        if p.get("note"):
            r.append(f"         ⚠️ {p['note']}")
    return "\n".join(r)


def generate_advice(scan_result, growth_mode, llm_chat_fn, boom_mode=False,
                    progress_callback=None, equity=None):
    """生成投资建议: 硬规则计划 + LLM 定性分析。

    equity: 账户总资产（用于把仓位上限换算成可买金额）。GUI 传 portfolio.total_equity()。
    """
    def log(m):
        if progress_callback: progress_callback(m)

    cands = scan_result.get("candidates_full") or []
    if not cands:
        return "⚠️ 无候选数据，请先扫描"

    # 成长/爆发模式按营收增速排序，价值模式保持 ROE 序
    if growth_mode or boom_mode:
        cands = sorted(cands, key=lambda x: x.get('rev_growth') or 0, reverse=True)

    summary = f"覆盖{scan_result.get('industry_count',0)}行业, {scan_result.get('total_stocks',0)}只股票"

    log("计算风控计划...")
    plans = compute_rule_based_plan(cands, growth_mode, boom_mode, equity=equity)

    # 计算数据截止期
    from scanner import _report_quarter_dates
    q, _, _ = _report_quarter_dates()
    q_map = {"0331": "Q1", "0630": "Q2", "0930": "Q3", "1231": "Q4"}
    q_label = q_map.get(q[4:], q[:4])
    data_period = f"{q[:4]}年{q_label}"

    log("生成定性分析...")
    prompt = build_qualitative_prompt(cands, plans, growth_mode, summary, data_period)
    try:
        analysis = llm_chat_fn([{"role": "user", "content": prompt}],
                               temperature=0.4, max_tokens=2000)
    except Exception as e:
        analysis = f"(定性分析生成失败: {e})"

    report = []
    report.append("=" * 64)
    report.append("  投资建议 — 风控硬规则 + AI 定性分析")
    report.append(f"  生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 财报截止: {data_period}")
    report.append(f"  模式: {'爆发/卫星' if boom_mode else ('成长股' if growth_mode else '价值股')}")
    report.append("=" * 64)
    report.append("")
    report.append(_fmt_plan_table(plans))
    report.append("")
    report.append("-" * 64)
    report.append(analysis)
    report.append("")
    report.append("-" * 64)
    report.append("说明: 仓位/止损为系统按三仓规则计算的纪律约束(可复现)；")
    report.append("定性分析由 AI 生成，仅供研究参考，均不构成投资建议。买卖由你自行决策。")
    report.append("卫星仓请只用可承受归零的资金。")
    return "\n".join(report)
