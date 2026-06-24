#!/usr/bin/env python3
"""
深度研究模块 - 对候选个股生成 6-12 月前瞻预期

流程:
1. 抓取基本面: 主营业务 + 财务摘要(近5期扣非/营收/ROE趋势)
2. 抓取新闻素材(尽力而为，东财源在Windows可能不可用)
3. 喂给 LLM 生成 6-12 月产品/经营前瞻预期

依赖: akshare(基本面) + llm_client(前瞻分析)
"""
import akshare as ak
import pandas as pd
import scanner
import llm_client


def fetch_fundamentals(code, timeout=30):
    """抓取主营业务 + 财务趋势"""
    data = {"code": code, "main_business": None, "financials": None}

    # 主营业务
    try:
        df = scanner._fetch_with_timeout(ak.stock_zyjs_ths, timeout, symbol=code)
        if df is not None and len(df) > 0:
            row = df.iloc[0]
            data["main_business"] = {
                "business": str(row.get("主营业务", "")),
                "products": str(row.get("产品类型", "")),
            }
    except Exception:
        pass

    # 财务趋势(近5期)
    try:
        df = scanner._fetch_with_timeout(
            ak.stock_financial_abstract_ths, timeout,
            symbol=code, indicator="按报告期"
        )
        if df is not None and len(df) > 0:
            cols = ['报告期', '净利润', '净利润同比增长率', '扣非净利润',
                    '扣非净利润同比增长率', '营业总收入', '营业总收入同比增长率', '净资产收益率']
            avail = [c for c in cols if c in df.columns]
            recent = df[avail].tail(5)
            data["financials"] = recent.to_dict('records')
    except Exception:
        pass

    return data


def fetch_news(code, name, timeout=20):
    """抓取个股新闻标题(尽力而为)。东财源在Windows常不可用，失败返回空。"""
    titles = []
    try:
        df = scanner._fetch_with_timeout(ak.stock_news_em, timeout, symbol=code)
        if df is not None and len(df) > 0:
            for _, row in df.head(10).iterrows():
                t = row.get("新闻标题") or row.get("标题")
                if t:
                    titles.append(str(t))
    except Exception:
        pass
    return titles


def build_prompt(stock, fundamentals, news_titles):
    """构造给 LLM 的研究 prompt"""
    code = stock["code"]
    name = stock["name"]
    industry = stock.get("industry", "")
    roe = stock.get("roe", "")
    pe = stock.get("pe")
    pe_str = f"{pe:.1f}" if pe else "未知"
    mktcap = stock.get("mktcap")
    mv_str = f"{mktcap:.0f}亿" if mktcap else "未知"

    lines = [
        f"你是一名资深A股行业研究员。请基于以下信息，对【{name}({code})】未来6-12个月的产品与经营做出前瞻预期分析。",
        f"",
        f"## 基本信息",
        f"- 所属行业: {industry}",
        f"- 最新ROE: {roe}%  |  TTM市盈率: {pe_str}  |  流通市值: {mv_str}",
    ]

    if fundamentals.get("main_business"):
        mb = fundamentals["main_business"]
        lines.append(f"- 主营业务: {mb['business']}")
        lines.append(f"- 产品类型: {mb['products']}")

    if fundamentals.get("financials"):
        lines.append(f"\n## 近期财务趋势(按报告期)")
        for f in fundamentals["financials"]:
            period = f.get("报告期", "")
            rev = f.get("营业总收入", "")
            rev_g = f.get("营业总收入同比增长率", "")
            np_ = f.get("扣非净利润", "")
            np_g = f.get("扣非净利润同比增长率", "")
            roe_p = f.get("净资产收益率", "")
            lines.append(f"- {period}: 营收{rev}(同比{rev_g}) 扣非净利{np_}(同比{np_g}) ROE{roe_p}")

    if news_titles:
        lines.append(f"\n## 近期新闻标题")
        for t in news_titles[:10]:
            lines.append(f"- {t}")
    else:
        lines.append(f"\n## 近期新闻\n(未获取到新闻数据，请基于行业常识与财务趋势分析)")

    lines.append(f"""
## 分析要求
请输出结构化分析(每部分2-4句，务实不空谈):

**1. 业务现状**: 主营产品的市场地位与盈利质量(结合扣非趋势判断盈利是否可持续)

**2. 行业景气度**: {industry}行业未来6-12月的供需/政策/技术趋势

**3. 6-12月产品预期**: 公司可能的新品/产能/订单催化或风险

**4. 经营预期**: 营收/利润趋势研判(注意识别周期顶部信号——若近期同比暴增可能不可持续)

**5. 关键风险**: 2-3个需要警惕的下行风险

**6. 综合结论**: 一句话给出关注度评级(重点关注/谨慎关注/观望)及核心逻辑

## 严格要求(防止编造)
- **只能基于上面提供的数据和你的公开知识进行分析**。
- **凡是上面数据未提供的具体数字(如订单金额、产能、市占率、机构目标价等)，绝对不要编造**；如需提及，必须写明"(注:此为推测，未经数据验证)"。
- 区分【事实】(来自上方数据)与【推测】(你的判断)，在涉及前瞻判断时用"预计/可能/或将"等措辞。
- 不要给出具体目标价或买卖点。
- 你的分析仅供研究参考，不构成投资建议。""")

    return "\n".join(lines)


def research_stock(stock, progress_callback=None):
    """对单只股票做深度研究。stock 含 code/name/industry/roe/pe/mktcap"""
    def log(m):
        if progress_callback:
            progress_callback(m)

    code = stock["code"]
    name = stock["name"]
    log(f"  [{code} {name}] 抓取基本面...")
    fundamentals = fetch_fundamentals(code)

    log(f"  [{code} {name}] 抓取新闻...")
    news = fetch_news(code, name)

    log(f"  [{code} {name}] LLM 前瞻分析...")
    prompt = build_prompt(stock, fundamentals, news)
    analysis = llm_client.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=1500
    )

    return {
        "code": code,
        "name": name,
        "industry": stock.get("industry"),
        "has_news": len(news) > 0,
        "has_fundamentals": fundamentals.get("financials") is not None,
        "news_count": len(news),
        "roe": stock.get("roe"),
        "deduct_roe": stock.get("deduct_roe"),
        "pe": stock.get("pe"),
        "mktcap": stock.get("mktcap"),
        "analysis": analysis,
    }


def research_candidates(candidates, top_n=10, progress_callback=None):
    """对候选池前 N 只做深度研究"""
    def log(m):
        if progress_callback:
            progress_callback(m)
        else:
            print(m)

    if not llm_client.is_configured():
        raise RuntimeError("未配置 LLM API key。请在 config.json 填写 api_key。")

    targets = candidates[:top_n]
    results = []
    for i, stock in enumerate(targets, 1):
        log(f"研究 {i}/{len(targets)}: {stock['code']} {stock['name']}")
        try:
            res = research_stock(stock, progress_callback)
            results.append(res)
        except Exception as e:
            results.append({
                "code": stock["code"], "name": stock["name"],
                "industry": stock.get("industry"),
                "analysis": f"⚠️ 研究失败: {e}",
                "has_news": False, "has_fundamentals": False,
            })
    return results


def build_research_report(results, scan_summary=""):
    from datetime import datetime
    r = []
    r.append("=" * 64)
    r.append("  A股科技+新能源 深度研究报告")
    r.append(f"  生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  LLM驱动前瞻分析")
    r.append("=" * 64)
    r.append("\n> ⚠️ **AI 生成内容免责声明**")
    r.append("> 以下分析由大语言模型基于公开财务数据与新闻标题生成，**可能包含事实错误或幻觉**。")
    r.append("> 所有前瞻判断均为模型推测，非确定性结论。投资决策前**务必自行核实关键数据**。")
    if scan_summary:
        r.append(f"\n{scan_summary}")
    r.append(f"\n本报告对候选池前 {len(results)} 只个股做 6-12 月前瞻分析。\n")

    for i, res in enumerate(results, 1):
        r.append(f"\n{'─'*60}")
        flags = []
        if not res.get("has_fundamentals"):
            flags.append("⚠️基本面数据不全")
        if not res.get("has_news"):
            flags.append("⚠️无新闻")
        flag_str = f"  [{' '.join(flags)}]" if flags else ""
        r.append(f"### {i}. {res['name']} ({res['code']})  —  {res.get('industry','')}{flag_str}")
        r.append(f"{'─'*60}")
        # 数据来源行(让用户知道分析基于什么)
        roe = res.get("roe")
        droe = res.get("deduct_roe")
        pe = res.get("pe")
        mv = res.get("mktcap")
        nc = res.get("news_count", 0)
        src = []
        if roe is not None:
            src.append(f"ROE {roe:.1f}%")
        if droe is not None:
            src.append(f"扣非ROE {droe:.1f}%")
        if pe is not None:
            src.append(f"PE {pe:.1f}")
        if mv is not None:
            src.append(f"市值 {mv:.0f}亿")
        src.append(f"财报{'✓' if res.get('has_fundamentals') else '✗'}")
        src.append(f"新闻{nc}条")
        r.append(f"*分析依据: {' | '.join(src)} (巨潮+新浪+同花顺)*\n")
        r.append(res["analysis"])

    r.append(f"\n\n{'='*64}")
    r.append("风险提示: 本报告由 AI 基于公开数据生成，仅供研究参考，不构成投资建议。")
    r.append("AI 分析可能存在事实错误或幻觉，请务必自行核实关键信息。")
    r.append("数据来源: 巨潮资讯(财报) + 新浪财经(行情) + 同花顺(财务摘要)。")
    r.append("=" * 64)
    return "\n".join(r)


if __name__ == "__main__":
    # 测试单只
    test_stock = {
        "code": "688111", "name": "金山办公", "industry": "软件开发",
        "roe": 15.7, "pe": 28.9, "mktcap": 1053,
    }
    print("测试深度研究...")
    if not llm_client.is_configured():
        print("⚠️ 未配置 API key，仅测试数据抓取与 prompt 构造")
        f = fetch_fundamentals(test_stock["code"])
        n = fetch_news(test_stock["code"], test_stock["name"])
        print("\n--- Prompt ---")
        print(build_prompt(test_stock, f, n))
    else:
        res = research_stock(test_stock, progress_callback=lambda m: print(m))
        print("\n" + res["analysis"])
