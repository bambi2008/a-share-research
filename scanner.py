#!/usr/bin/env python3
"""
A股科技+新能源 扫描核心模块 (scanner)
数据源: 巨潮资讯 + 新浪财经

改进点:
- PE 用 TTM(滚动四季) 替代单季×4，消除周期股失真
- 行业集中度提示
- ROE 局限性说明
- 支持超时 + 取消
"""
from datetime import datetime, timedelta
import concurrent.futures
import os

# ── 行业列表(从 industries.json 加载，不存在则用默认) ──
def _load_industries():
    import json, sys
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "industries.json")
    if getattr(sys, 'frozen', False):
        p = os.path.join(os.path.dirname(sys.executable), "industries.json")
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f).get("industries", [])
    except Exception:
        return [
            "半导体", "电子化学品Ⅱ", "软件开发", "IT服务Ⅱ",
            "通信服务", "通信设备", "计算机设备",
            "消费电子", "光学光电子", "其他电子Ⅱ", "军工电子Ⅱ",
            "电池", "光伏设备", "电网设备",
            "风电设备", "电力", "自动化设备",
            "互联网电商", "厨卫电器",
        ]

TARGET_INDUSTRIES = _load_industries()

# ── 配置 ──
FILTER_PE_MIN, FILTER_PE_MAX = 3, 40
FILTER_ROE_MIN = 5
FILTER_DEDUCT_ROE_MIN = 3
FILTER_MV_MIN, FILTER_MV_MAX = 50, 10000
ENABLE_MKTCAP = True
ENABLE_DEDUCT_ROE = True
TOP_N = 30
FETCH_TIMEOUT = 180

# 成长股模式: 放宽PE+ROE，关注营收增长
GROWTH_MODE = False
GROWTH_PE_MAX = 200     # 成长股PE上限更宽
GROWTH_ROE_MIN = 0      # 成长股允许不赚钱
GROWTH_REV_MIN = 20     # 但营收必须增长>20%

# 爆发模式: 寻找翻番潜力的高成长股(核心卫星的"卫星"部分)
# 设计依据:
#   · 黄仁勋 GTC 2026: AI算力需求至少1万亿美元到2027
#   · Altman: "基础设施是最大瓶颈" — 成长公司高PE/负PE是投资期正常现象
#   · Musk/雷军: 2026=人形机器人量产元年,供应链爆发
#   · 李开复: 2026=企业AI Agent上岗元年,To B场景营收爆发
#   · 黄仁勋: "Agent不断生成子Agent,推理算力指数增长"
#   · 低空经济/eVTOL: 2027商业化元年,沃兰特融资50亿
#   · AI制药: 晶泰首次盈利,首个AI全流程药进入III期
BOOM_MODE = False
BOOM_REV_MIN = 30       # 营收增长>30%(抓住爆发拐点)
BOOM_SECTORS = [         # 只在这些爆发行业里找(基于产业研判)
    # AI产业链上游
    "半导体", "软件开发", "IT服务Ⅱ", "通信设备", "计算机设备",
    "自动化设备", "光学光电子", "消费电子",
    # 机器人与航空(低空经济)
    "航空装备Ⅱ", "航天装备Ⅱ",
    # 新能源
    "电池", "光伏设备", "电网设备",
    # AI制药 + 合成生物学
    "化学制药", "生物制品", "医疗器械", "医疗服务",
    # 新材料
    "金属新材料", "非金属材料Ⅱ",
]


from data_source import INDICES  # 指数列表已内聚到 data_source（含 baostock 备用 code）


class ScanCancelled(Exception):
    """扫描被用户取消"""
    pass


def _fetch_with_timeout(fn, timeout, *args, **kwargs):
    """在子线程执行 fn，超时则抛 TimeoutError（子线程作为 daemon 自然回收）"""
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, *args, **kwargs)
    try:
        result = fut.result(timeout=timeout)
        ex.shutdown(wait=False)
        return result
    except concurrent.futures.TimeoutError:
        ex.shutdown(wait=False)
        raise TimeoutError(f"数据请求超时(>{timeout}s)")
    except Exception as e:
        # zlib 解压错误等数据损坏异常
        ex.shutdown(wait=False)
        msg = str(e)
        if "decompress" in msg.lower() or "header check" in msg.lower() or "error -3" in msg.lower():
            raise RuntimeError(f"数据传输损坏(可能是代理/VPN导致): {msg[:80]}")
        raise


def _fetch_float_mktcap(ak, code):
    """获取流通市值(亿元)。用新浪日线的 outstanding_share × 最新收盘价。
    返回 None 表示获取失败（网络/无数据）。
    """
    # 新浪日线 symbol 需带市场前缀
    if code.startswith(('60', '68', '90', '11', '51')):
        sym = f"sh{code}"
    elif code.startswith(('00', '30', '12', '15', '20')):
        sym = f"sz{code}"
    elif code.startswith(('8', '4', '92')):
        sym = f"bj{code}"
    else:
        sym = f"sh{code}"
    try:
        df = _fetch_with_timeout(
            ak.stock_zh_a_daily, 20, symbol=sym,
            start_date="20260101", adjust=""
        )
        if df is None or len(df) == 0:
            return None
        latest = df.iloc[-1]
        shares = latest.get('outstanding_share')
        close = latest.get('close')
        if shares and close:
            return close * shares / 1e8  # 流通市值(亿)
        return None
    except Exception:
        return None


def _parse_cn_amount(s):
    """解析中文金额字符串(如'21.71亿'、'-3.2万'、'15.70%')为float。失败返None"""
    if s is None:
        return None
    s = str(s).strip().replace(',', '').replace('%', '')
    if s in ('', '-', 'False', 'nan', 'None'):
        return None
    mult = 1.0
    if s.endswith('亿'):
        mult = 1e8; s = s[:-1]
    elif s.endswith('万'):
        mult = 1e4; s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _fetch_deduct_roe(ak, code, fallback_roe=None):
    """获取扣非ROE(%)。同花顺财务摘要有扣非净利润+净利润+ROE，
    扣非ROE ≈ 净资产收益率 × (扣非净利润 / 净利润)。
    返回 None 表示获取失败。
    """
    try:
        df = _fetch_with_timeout(
            ak.stock_financial_abstract_ths, 25,
            symbol=code, indicator="按报告期"
        )
        if df is None or len(df) == 0:
            return None
        latest = df.iloc[-1]
        roe = _parse_cn_amount(latest.get('净资产收益率'))
        np_ = _parse_cn_amount(latest.get('净利润'))
        deduct_np = _parse_cn_amount(latest.get('扣非净利润'))
        if roe is None:
            roe = fallback_roe
        if roe is None or np_ is None or deduct_np is None or np_ == 0:
            return None
        # 扣非占比(可能>1或<0)
        ratio = deduct_np / np_
        return roe * ratio
    except Exception:
        return None


def _report_quarter_dates(now=None):
    """计算最近已披露的报告期 + 用于TTM的三个报告期
    返回 (latest_q, prev_annual, prev_year_same_q)
    例: 当前2026Q2 → latest=2026Q1(20260331), annual=2025(20251231), prev_q=2025Q1(20250331)
    """
    if now is None:
        now = datetime.now()
    y = now.year
    m = now.month
    # 季报披露滞后：粗略按月份判断最近已出的报告期
    if m <= 4:        # Q4年报/次年Q1还没全出 → 用上一年Q3
        latest = f"{y-1}0930"
    elif m <= 8:      # Q1已出
        latest = f"{y}0331"
    elif m <= 10:     # 中报已出
        latest = f"{y}0630"
    else:             # Q3已出
        latest = f"{y}0930"

    ly = int(latest[:4])
    md = latest[4:]
    prev_annual = f"{ly-1}1231"
    prev_year_same_q = f"{ly-1}{md}"
    return latest, prev_annual, prev_year_same_q


def run_scan(progress_callback=None, cancel_check=None):
    """执行扫描。
    progress_callback(msg): 进度回调
    cancel_check(): 返回 True 表示用户请求取消
    返回结果 dict。
    """
    import akshare as ak
    import pandas as pd

    def log(msg):
        if progress_callback:
            progress_callback(msg)

    def check_cancel():
        if cancel_check and cancel_check():
            raise ScanCancelled("用户取消扫描")

    # ── 1. 大盘指数 ──
    # ── 1. 大盘指数（多源容灾） ──
    import data_source
    index_data, idx_src = data_source.get_index_data(FETCH_TIMEOUT)
    for name in index_data:
        c = index_data[name].get("close")
        ch = index_data[name].get("chg_pct")
        if c:
            log(f"  {name}: {c:.0f} ({ch:+.1f}%)")
    if not index_data:
        log("  ⚠️ 指数获取失败(所有源)")
    log(f"  指数源: {idx_src}")

    # ── 2. 季报(TTM需3期) ──
    q_latest, q_annual, q_prev = _report_quarter_dates()
    log(f"2/5 季报(TTM: {q_latest}/{q_annual}/{q_prev})...")

    check_cancel()
    df_latest = _fetch_with_timeout(ak.stock_yjbb_em, FETCH_TIMEOUT, date=q_latest)
    log(f"  最新期 {q_latest}: {len(df_latest)} 只")

    check_cancel()
    try:
        df_annual = _fetch_with_timeout(ak.stock_yjbb_em, FETCH_TIMEOUT, date=q_annual)
        df_prev = _fetch_with_timeout(ak.stock_yjbb_em, FETCH_TIMEOUT, date=q_prev)
        ttm_available = True
        log(f"  TTM基期就绪: {len(df_annual)}/{len(df_prev)} 只")
    except Exception as e:
        df_annual = df_prev = None
        ttm_available = False
        log(f"  ⚠️ TTM基期获取失败，PE降级为单季×4")

    # 构建 EPS 映射
    def eps_map(df):
        m = {}
        if df is None:
            return m
        for _, r in df.iterrows():
            code = str(r['股票代码'])
            eps = r.get('每股收益')
            if not pd.isna(eps):
                m[code] = eps
        return m

    eps_latest = eps_map(df_latest)
    eps_annual = eps_map(df_annual)
    eps_prev = eps_map(df_prev)

    def ttm_eps(code):
        """TTM EPS = 最新累计 + 上年年报 - 上年同期累计"""
        if ttm_available and code in eps_latest and code in eps_annual and code in eps_prev:
            return eps_latest[code] + eps_annual[code] - eps_prev[code]
        # 降级：单季累计年化（仅最新期可用时）
        if code in eps_latest:
            # latest 是累计值，按报告期月份年化
            month = int(q_latest[4:6])
            factor = 12 / month  # Q1=4, H1=2, Q3=4/3, 年报=1
            return eps_latest[code] * factor
        return None

    # ── 3. 实时价格（多源容灾） ──
    log("3/5 实时行情...")
    check_cancel()

    # ── 2.5 热门概念板块 ──
    log("2.5 热门概念...")
    check_cancel()
    concept_codes_all = set()
    code_concepts = {}
    try:
        import concept_stocks
        concept_stocks_all, code_concepts = concept_stocks.get_concept_codes(
            progress_callback=lambda m: log(f"  {m}"))
        concept_codes_all = concept_stocks_all
        log(f"  概念股: {len(concept_codes_all)} 只 (6个概念板块)")
    except Exception as e:
        log(f"  概念板块跳过: {e}")

    # ── 2.6 扩展数据（并行）：高管增减持 + 宏观 + 分红 ──
    log("2.6 扩展数据...")
    check_cancel()
    insider_alerts = {}
    macro_data = {}
    dividend_data = {}

    def _fetch_insider():
        try:
            import insider_check
            return insider_check.fetch_insider_changes(
                progress_callback=lambda m: log(f"  {m}"))
        except Exception as e:
            log(f"  高管增减持跳过: {e}")
            return {}

    def _fetch_macro():
        try:
            import macro_context
            return macro_context.fetch_macro_context(
                progress_callback=lambda m: log(f"  {m}"))
        except Exception as e:
            log(f"  宏观跳过: {e}")
            return {}

    def _fetch_dividend():
        try:
            import dividend_screen
            return dividend_screen.fetch_dividend_data(
                progress_callback=lambda m: log(f"  {m}"))
        except Exception as e:
            log(f"  分红跳过: {e}")
            return {}

    # 并行获取（各模块内部有缓存，不会重复请求）
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f_insider = pool.submit(_fetch_insider)
        f_macro = pool.submit(_fetch_macro)
        f_dividend = pool.submit(_fetch_dividend)
        insider_alerts = f_insider.result(timeout=30)
        macro_data = f_macro.result(timeout=30)
        dividend_data = f_dividend.result(timeout=30)

    import data_source as ds
    # 目标股票池：目标行业 + 概念成分股
    target_codes = [
        str(r['股票代码']) for _, r in df_latest.iterrows()
        if str(r.get('所处行业', '')) in TARGET_INDUSTRIES
    ]
    # 合并概念股代码
    for cc in concept_codes_all:
        if cc not in target_codes:
            target_codes.append(cc)
    price_map, price_src = ds.get_price_map(FETCH_TIMEOUT, codes=target_codes)
    log(f" 价格覆盖: {len(price_map)} 只 (源: {price_src})")

    # ── 4. 筛选 ──
    log("4/5 筛选...")
    check_cancel()
    candidates = []
    industry_stats = {}

    for _, row in df_latest.iterrows():
        code = str(row['股票代码'])
        industry = str(row.get('所处行业', ''))

        # 概念股：即使行业不匹配也保留（前提是代码在概念成分中）
        is_concept = code in concept_codes_all
        if industry == 'nan' or (industry not in TARGET_INDUSTRIES and not is_concept):
            continue
        industry_stats[industry] = industry_stats.get(industry, 0) + 1

        roe = row.get('净资产收益率')
        # 爆发模式: 不看ROE, 看重营收爆发
        if BOOM_MODE:
            if industry not in BOOM_SECTORS:
                continue
            rev_g = row.get('营业总收入-同比增长')
            if pd.isna(rev_g) or rev_g < BOOM_REV_MIN:
                continue
        else:
            roe_min = GROWTH_ROE_MIN if GROWTH_MODE else FILTER_ROE_MIN
            if pd.isna(roe) or roe < roe_min:
                continue

        # 成长股模式: 营收增长要求
        rev_g = row.get('营业总收入-同比增长')
        if GROWTH_MODE and not BOOM_MODE:
            if pd.isna(rev_g) or rev_g < GROWTH_REV_MIN:
                continue

        code = str(row['股票代码'])
        price = price_map.get(code)
        teps = ttm_eps(code)
        if teps is None or teps <= 0 or not price:
            pe = None
        else:
            pe = price / teps

        # 爆发模式: 不看PE
        if not BOOM_MODE:
            pe_max = GROWTH_PE_MAX if GROWTH_MODE else FILTER_PE_MAX
            if pe is not None and (pe < FILTER_PE_MIN or pe > pe_max):
                continue

        profit_g = row.get('净利润-同比增长')

        # 概念标签
        concepts = code_concepts.get(code, [])

        # 高管增减持检查
        insider_flag = None
        insider_detail = ""
        if insider_alerts:
            ia = insider_alerts.get(code)
            if ia:
                insider_flag = ia["alert"]
                insider_detail = f"高管{ia['alert']}告警(卖{ia['sell_shares']}股/卖比{ia['sell_ratio']}%)"

        # 分红数据
        div_info = {}
        if dividend_data:
            import dividend_screen
            div_info = dividend_screen.get_dividend_info(code, dividend_data, price)

        candidates.append({
            'code': code, 'name': str(row['股票简称']),
            'pe': pe, 'roe': roe, 'price': price,
            'industry': industry,
            'rev_growth': rev_g if not pd.isna(rev_g) else None,
            'profit_growth': profit_g if not pd.isna(profit_g) else None,
            'concepts': concepts,
            'insider_flag': insider_flag,
            'insider_detail': insider_detail,
            'div_yield': div_info.get('div_yield'),
            'div_count': div_info.get('div_count'),
            'avg_div': div_info.get('avg_div'),
        })

    if BOOM_MODE:
        candidates.sort(key=lambda x: x.get('rev_growth') or 0, reverse=True)
    else:
        candidates.sort(key=lambda x: x['roe'] or 0, reverse=True)

    # ── 4.5 候选逐只补全: 市值 + 扣非ROE（合并到一个循环） ──
    if (ENABLE_MKTCAP or ENABLE_DEDUCT_ROE) and candidates:
        log(f"  补全市值/扣非ROE({len(candidates)}只)...")
        filtered = []
        for i, c in enumerate(candidates):
            check_cancel()
            keep = True

            # 市值
            if ENABLE_MKTCAP:
                mv = _fetch_float_mktcap(ak, c['code'])
                c['mktcap'] = mv
                if mv is not None and not (FILTER_MV_MIN <= mv <= FILTER_MV_MAX):
                    keep = False
            else:
                c['mktcap'] = None

            # 扣非ROE — 确定性保障: 接口失败用季度ROE fallback, 不一致时也保留
            if ENABLE_DEDUCT_ROE and keep:
                droe = _fetch_deduct_roe(ak, c['code'], fallback_roe=c['roe'])
                # 接口失败: 用季度ROE, 不剔除 (宁可多留不可因网络原因漏掉)
                if droe is None:
                    droe = c['roe'] if c['roe'] is not None else FILTER_DEDUCT_ROE_MIN
                c['deduct_roe'] = droe
                if droe < FILTER_DEDUCT_ROE_MIN:
                    keep = False
            else:
                c['deduct_roe'] = None

            if keep:
                filtered.append(c)
            if (i + 1) % 10 == 0:
                log(f"    进度 {i+1}/{len(candidates)}")
        removed = len(candidates) - len(filtered)
        candidates = filtered
        log(f"  市值+扣非ROE过滤: 剔除 {removed} 只, 剩 {len(candidates)} 只")
    else:
        for c in candidates:
            c['mktcap'] = None
            c['deduct_roe'] = None

    # 行业集中度（候选池层面）
    cand_industry = {}
    for c in candidates:
        cand_industry[c['industry']] = cand_industry.get(c['industry'], 0) + 1
    top_industry, top_count = (max(cand_industry.items(), key=lambda x: x[1])
                                if cand_industry else (None, 0))
    concentration = (top_count / len(candidates) * 100) if candidates else 0

    log(f"  行业: {len(industry_stats)}个, 候选: {len(candidates)}只")

    # ── 持仓体检 ──
    import position
    positions, __alerts = position.check_positions(price_map)

    # ── 5. 生成报告 ──
    log("5/5 生成报告...")
    report = _build_report(index_data, industry_stats, candidates, cand_industry,
                           top_industry, concentration, ttm_available, q_latest, positions)
    # ── 扩展: 动量排名 + 卫星凸性 + 三仓风控面板(失败不影响主报告) ──
    try:
        import enrich_report
        report += "\n\n" + enrich_report.build_extension(candidates, price_map)
    except Exception as _e:
        log(f" ⚠️ 扩展模块跳过: {_e}")
    
    # 保存
    now = datetime.now()
    week_num = now.isocalendar()[1]
    import sys
    if getattr(sys, 'frozen', False):
        script_dir = os.path.dirname(sys.executable)
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    reports_dir = os.path.join(script_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"week_{week_num}.md")
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
    except Exception as e:
        log(f"  ⚠️ 报告保存失败: {e} (路径:{report_path})")
        print(f"DEBUG: script_dir={script_dir}, reports_dir={reports_dir}", file=sys.stderr)

    return {
        "report": report,
        "report_path": report_path,
        "index_data": index_data,
        "candidate_count": len(candidates),
        "candidates_full": candidates,
        "industry_count": len(industry_stats),
        "total_stocks": sum(industry_stats.values()),
        "concentration": concentration,
        "top_industry": top_industry,
        "ttm_available": ttm_available,
        "scan_time": now.strftime('%Y-%m-%d %H:%M'),
        "macro_data": macro_data,
        "insider_alerts": insider_alerts,
        "data_sources": {
            "index": idx_src,
            "price": price_src,
            "quarterly": "巨潮资讯",
        }
    }


def _build_report(index_data, industry_stats, candidates, cand_industry,
                  top_industry, concentration, ttm_available, q_latest, positions=None):
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=4)
    week_num = now.isocalendar()[1]
    pe_method = "TTM(滚动四季)" if ttm_available else "单季年化(降级)"

    r = []
    r.append("=" * 64)
    r.append(f"  A股科技+新能源 周度扫描报告 v4")
    r.append(f"  {week_start.strftime('%Y.%m.%d')} - {week_end.strftime('%Y.%m.%d')}  |  第{week_num}周")
    r.append(f"  生成: {now.strftime('%Y-%m-%d %H:%M')}  |  数据: 巨潮资讯 + 新浪财经")
    r.append(f"  PE算法: {pe_method}  |  报告期: {q_latest}")
    r.append("=" * 64)

    r.append("## 一、大盘概况\n")
    for name, info in index_data.items():
        close = info['close']
        chg = info['chg_pct']
        date = info['date']
        if close:
            r.append(f"| {name} | {close:>10.2f} | {chg:>+8.2f}% | {date} |")
        else:
            r.append(f"| {name} | - | - | 数据获取失败 |")

    r.append("\n## 一、持仓体检\n")
    if positions:
        r.append("| 代码 | 名称 | 成本 | 现价 | 盈亏 | 买入日 |")
        r.append("|------|------|------|------|------|--------|")
        for p in positions:
            pnl_str = f"{p['pnl_pct']:+.1f}%" if p['pnl_pct'] is not None else "-"
            price_str = f"{p['price']:.2f}" if p['price'] else "-"
            r.append(f"| {p['code']} | {p['name']} | {p['cost']} | {price_str} | {pnl_str} | {p['date']} |")
            for alert in p.get("alerts", []):
                r.append(f"  ⚠️ {alert}")
    else:
        r.append("  (未配置持仓)")

    r.append("\n## 二、行业扫描\n")
    r.append("| 行业 | 股票数 |")
    r.append("|------|--------|")
    for ind in sorted(industry_stats.keys()):
        r.append(f"| {ind} | {industry_stats[ind]} |")
    r.append(f"| **合计** | **{sum(industry_stats.values())}** |")

    r.append(f"\n## 三、候选标的池\n")
    mv_desc = f" | 流通市值 {FILTER_MV_MIN}-{FILTER_MV_MAX}亿" if ENABLE_MKTCAP else ""
    if BOOM_MODE:
        filter_desc = f"💥 爆发模式(卫星): 营收>{BOOM_REV_MIN}% | 不限PE/ROE | 关注营收加速度"
        r.append(f"{filter_desc}  |  共 **{len(candidates)}** 只\n")
        r.append(f"\n> 设计依据: 黄仁勋GTC2026(算力万亿到2027)、Musk/雷军(机器人量产元年)、"
                 f"李开复(企业AI Agent上岗)、低空经济2027商业化\n")
    elif GROWTH_MODE:
        filter_desc = f"成长模式: PE<{GROWTH_PE_MAX} | 营收增长>{GROWTH_REV_MIN}%{mv_desc}"
        r.append(f"{filter_desc}  |  共 **{len(candidates)}** 只\n")
    else:
        filter_desc = f"筛选(核心): PE {FILTER_PE_MIN}-{FILTER_PE_MAX} | ROE > {FILTER_ROE_MIN}%{mv_desc}"
        r.append(f"{filter_desc}  |  共 **{len(candidates)}** 只\n")

    # 行业集中度警告
    if top_industry and concentration >= 30:
        r.append(f"> ⚠️ **行业集中度偏高**: {top_industry} 占候选池 {concentration:.0f}% "
                 f"({cand_industry[top_industry]}/{len(candidates)})，注意分散风险。\n")

    if candidates:
        r.append("| 代码 | 名称 | PE | ROE% | 扣非ROE% | 价格 | 流通市值(亿) | 行业 | 营收增% | 利润增% |")
        r.append("|------|------|-----|------|---------|------|------|------|---------|---------|")
        for c in candidates[:TOP_N]:
            pe_str = f"{c['pe']:.1f}" if c['pe'] else "-"
            price_str = f"{c['price']:.2f}" if c['price'] else "-"
            mv_str = f"{c['mktcap']:.0f}" if c.get('mktcap') else "-"
            droe_str = f"{c['deduct_roe']:.1f}" if c.get('deduct_roe') is not None else "-"
            rev = f"{c['rev_growth']:.1f}" if c['rev_growth'] else "-"
            prof = f"{c['profit_growth']:.1f}" if c['profit_growth'] else "-"
            r.append(f"| {c['code']} | {c['name']} | {pe_str} | {c['roe']:.1f} | {droe_str} | {price_str} | {mv_str} | {c['industry']} | {rev} | {prof} |")

    r.append(f"\n## 四、下周关注\n")
    r.append("⏳ 待补充：政策事件、季报日历、解禁提醒")

    r.append(f"\n## 五、方法论局限\n")
    r.append("- **PE**: " + ("TTM滚动四季，已规避单季失真；但仍未剔除非经常性损益。" if ttm_available
              else "TTM基期数据缺失，降级为单季年化，**周期股PE严重失真，仅供参考**。"))
    r.append("- **ROE**: 未扣非，高ROE可能含一次性收益或高杠杆，需结合资产负债率与扣非净利润复核。")
    r.append("- **周期股警示**: 营收/利润同比暴增(如>300%)往往是周期顶部信号，ROE虚高不可持续。")
    r.append("- **无市值过滤**: 候选池未区分大/中/小盘，小市值流动性风险需自行评估。")
    r.append("- **无回测**: 本策略未做历史有效性验证。")

    r.append(f"\n---\n*风险提示: 本报告为初步筛选工具，不构成投资建议。*")

    return "\n".join(r)


if __name__ == "__main__":
    # CLI 模式
    result = run_scan(progress_callback=lambda m: print(f"  {m}"))
    print("\n" + result["report"])
    print(f"\n📄 已保存: {result['report_path']}")
