#!/usr/bin/env python3
"""
产业研报模块 — 内置版
扫描完成后自动搜索最新产业动态+地缘风险+内外需分析，LLM综合研判
"""
import urllib.request, json
from datetime import datetime


def search_news(queries, max_results=3):
    """用 DuckDuckGo HTML 搜索（无需 API key）。返回 [(title, url, snippet), ...]"""
    results = []
    for q in queries:
        try:
            url = f"https://html.duckduckgo.com/html/?q={urllib.request.quote(q)}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8")
            # 简单解析
            import re
            snippets = re.findall(r'class="result__snippet">(.+?)</a>', html, re.DOTALL)
            titles = re.findall(r'class="result__title".*?>(.+?)</a>', html, re.DOTALL)
            urls = re.findall(r'class="result__url".*?>(.+?)</', html, re.DOTALL)
            for i in range(min(len(titles), max_results)):
                t = re.sub(r'<[^>]+>', '', titles[i]).strip()
                s = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
                u = urls[i].strip() if i < len(urls) else ""
                results.append((t, u, s))
        except Exception:
            pass
    return results


def build_research_prompt(candidates, industries, search_results, scan_summary):
    """构造产业研报 prompt"""
    from datetime import datetime
    sep = "="*50
    lines = [
        "你是一名资深产业研究员。基于以下扫描结果和最新公开信息，",
        f"今天是 {datetime.now().strftime('%Y年%m月%d日')}，财务数据来自最新季报。",
        "对候选池涉及的行业做 6-12 个月产业前景研判，",
        "**特别关注外需依赖度和地缘政治风险**。",
        "注意：不要写'根据2025年Q1数据'这种话——数据就是最新的。说'最新财报'即可。",
        "",
        sep,
        "## 扫描概况",
        f"{scan_summary}",
        f"涉及行业: {', '.join(industries[:15])}",
        f"候选公司数: {len(candidates)}",
        "",
        sep,
        "## 最新产业动态（网络搜索结果）",
    ]
    if search_results:
        for t, u, s in search_results[:15]:
            lines.append(f"- {t}: {s[:120]}...")
    else:
        lines.append("(未获取到最新新闻)")

    lines.extend([
        "",
        sep,
        "## 分析要求",
        "",
        "请输出以下四个板块的结构化分析(每板块3-5条核心判断):",
        "格式: 纯文本不用markdown。用【一、】做标题，· 做条目，用箭头连接因果。直接输出，不要代码块包裹。",
        "",
        "**一、产业景气度**: 候选涉及的行业未来6-12月供需/技术/政策趋势",
        "",
        "**二、内外需分析（重要！）**: 逐行业判断——",
        "  - 内需依赖型: 纯国内市场驱动，受国内政策/消费影响",
        "  - 外需依赖型: 出口占比大，需评估中美关系/关税/制裁/实体清单风险",
        "  - 对每个外需依赖的行业，评估未来6-12月出口环境和可能的风险事件",
        "  - 标注哪些公司最可能受地缘政治影响",
        "",
        "**三、AI产业链机会**: 结合搜索到的产业动态,评估AI产业链各环节投资价值",
        "",
        "**四、综合研判**: 未来6-12月最值得关注的方向排序(前5)，每个方向一句话逻辑",
        "",
        "注意:",
        "- 引用搜索到的具体数据时标注来源",
        "- 地缘风险要具体(例如'若美国扩大芯片出口管制,则XX公司XX业务受影响')",
        "- 避免泛泛而谈,用具体行业/公司举例",
    ])
    return "\n".join(lines)


def generate_research_report(scan_result, llm_chat_fn, progress_callback=None):
    """
    生成产业研报。
    scan_result: scanner.run_scan 的返回值
    llm_chat_fn: msg → response 的 LLM 调用函数
    返回 markdown 报告文本
    """
    def log(m):
        if progress_callback: progress_callback(m)

    cands = scan_result.get("candidates_full") or []
    if not cands:
        return "⚠️ 无候选数据，请先扫描"

    industries = list(set(c.get("industry","") for c in cands if c.get("industry")))
    top5_names = [c["name"] for c in cands[:5]]

    # 搜索: 产业动态 + 地缘风险
    log("搜索产业动态...")
    search_queries = [
        f"AI 半导体 产业链 2026年6月 趋势",
        f"芯片出口管制 对华制裁 2026",
        f"新能源 光伏 电池 出口 关税 2026",
        f"人形机器人 具身智能 量产 2026",
    ]
    results = search_news(search_queries)

    # 摘要
    summary = f"候选{len(cands)}只, 覆盖{len(industries)}个行业, 代表公司: {', '.join(top5_names[:5])}"

    log("LLM研判中...")
    prompt = build_research_prompt(cands, industries, results, summary)

    # 调用 LLM
    analysis = llm_chat_fn([
        {"role": "user", "content": prompt}
    ], temperature=0.5, max_tokens=2500)

    # 组装报告
    from scanner import _report_quarter_dates
    q, _, _ = _report_quarter_dates()
    q_map = {"0331": "Q1", "0630": "Q2", "0930": "Q3", "1231": "Q4"}
    data_period = f"{q[:4]}年{q_map.get(q[4:], q[:4])}"

    report = []
    report.append("=" * 64)
    report.append("  产业深度研报 — AI产业链+内外需分析")
    report.append(f"  生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 财报截止: {data_period}")
    report.append("=" * 64)
    report.append(f"\n扫描基础: {summary}")
    report.append("\n---\n")
    report.append(analysis)
    report.append(f"\n\n---")
    report.append("*本研报由 AI 基于网络公开信息生成，包含推测性判断，不构成投资建议。*")
    report.append("*内外需分析基于当前公开信息，地缘政治局势变化可能快速改变结论。*")
    return "\n".join(report)


if __name__ == "__main__":
    # 简单测试
    r = search_news(["AI芯片 出口管制 2026"])
    print(f"搜索到 {len(r)} 条结果")
    for t, u, s in r:
        print(f"  {t}")
