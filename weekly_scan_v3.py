#!/usr/bin/env python3
"""
A股科技+新能源 周度扫描 v3
数据源: 巨潮(季报/ROE/行业) + 新浪(行情/指数)
改进: 大盘指数 / 精准行业匹配 / PE计算
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import os

# ── 配置 ──
FILTER_PE_MIN, FILTER_PE_MAX = 3, 40
FILTER_ROE_MIN = 5
TOP_N = 30  # 报告最多显示前N只

# 科技+新能源行业（精确匹配巨潮"所处行业"字段）
TARGET_INDUSTRIES = [
    "半导体", "电子化学品Ⅱ", "软件开发", "IT服务Ⅱ",
    "通信服务", "通信设备", "计算机设备",
    "消费电子", "光学光电子", "其他电子Ⅱ", "军工电子Ⅱ",
    "电池", "光伏设备", "电网设备",
    "风电设备", "电力", "自动化设备",
    "互联网电商", "厨卫电器",
]

# 指数配置
INDICES = [
    ("上证指数", "sh000001"),
    ("创业板指", "sz399006"),
    ("科创50", "sh000688"),
]

def main():
    print("🔍 A股科技+新能源 周度扫描 v3")
    
    # ── 1. 大盘指数（新浪） ──
    print("  1/4 大盘指数...")
    index_data = {}
    for name, sym in INDICES:
        try:
            df = ak.stock_zh_index_daily(symbol=sym)
            latest = df.iloc[-1]
            prev = df.iloc[-6] if len(df) >= 6 else df.iloc[0]  # ~一周前
            close = latest['close']
            chg = (close - prev['close']) / prev['close'] * 100
            index_data[name] = {"close": close, "chg_pct": chg, "date": str(latest['date'])[:10]}
            print(f"    {name}: {close:.2f} (周涨跌: {chg:+.2f}%)")
        except Exception as e:
            print(f"    {name}: ❌ {type(e).__name__}")
            index_data[name] = {"close": None, "chg_pct": None, "date": None}
    
    # ── 2. 季度财报（巨潮） ──
    print("  2/4 季度财报(巨潮)...")
    df_q = ak.stock_yjbb_em(date="20260331")
    print(f"    全A季报: {len(df_q)} 只")
    
    # ── 3. 实时价格（新浪） ──
    print("  3/4 实时行情(新浪)...")
    df_price = ak.stock_zh_a_spot()
    price_map = {}
    for _, row in df_price.iterrows():
        code = str(row['代码']).replace('bj','').replace('sh','').replace('sz','')
        price_map[code] = row['最新价']
    print(f"    价格覆盖: {len(price_map)} 只")
    
    # ── 4. 筛选 ──
    print("  4/4 筛选...")
    candidates = []
    industry_stats = {}
    
    for _, row in df_q.iterrows():
        industry = str(row.get('所处行业', ''))
        if industry == 'nan':
            continue
        
        # 行业精确匹配
        if industry not in TARGET_INDUSTRIES:
            continue
        industry_stats[industry] = industry_stats.get(industry, 0) + 1
        
        # ROE
        roe = row.get('净资产收益率')
        if pd.isna(roe) or roe < FILTER_ROE_MIN:
            continue
        
        # PE = 价格 / (每股收益 × 4)  年化估算
        code = str(row['股票代码'])
        eps = row.get('每股收益')
        price = price_map.get(code)
        if pd.isna(eps) or eps <= 0 or not price:
            pe = None
        else:
            pe = price / (eps * 4)
        
        # PE过滤（PE=None也保留，标注为"-"）
        if pe is not None and (pe < FILTER_PE_MIN or pe > FILTER_PE_MAX):
            continue
        
        rev_g = row.get('营业总收入-同比增长')
        profit_g = row.get('净利润-同比增长')
        
        candidates.append({
            'code': code, 'name': str(row['股票简称']),
            'pe': pe, 'roe': roe, 'price': price,
            'industry': industry,
            'rev_growth': rev_g if not pd.isna(rev_g) else None,
            'profit_growth': profit_g if not pd.isna(profit_g) else None,
        })
    
    candidates.sort(key=lambda x: x['roe'] or 0, reverse=True)
    
    # 行业统计
    print(f"    行业匹配: {len(industry_stats)} 个行业, {sum(industry_stats.values())} 只股票")
    print(f"    候选标的: {len(candidates)} 只")
    
    # ── 生成报告 ──
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=4)
    week_num = now.isocalendar()[1]
    
    report = []
    report.append("=" * 64)
    report.append(f"  A股科技+新能源 周度扫描报告 v3")
    report.append(f"  {week_start.strftime('%Y.%m.%d')} - {week_end.strftime('%Y.%m.%d')}  |  第{week_num}周")
    report.append(f"  生成: {now.strftime('%Y-%m-%d %H:%M')}  |  数据: 巨潮资讯 + 新浪财经")
    report.append("=" * 64)
    
    # 大盘
    report.append("\n## 一、大盘概况\n")
    for name, info in index_data.items():
        close = info['close']
        chg = info['chg_pct']
        date = info['date']
        if close:
            report.append(f"| {name} | {close:>10.2f} | {chg:>+8.2f}% | {date} |")
        else:
            report.append(f"| {name} | - | - | 数据获取失败 |")
    
    # 行业概览
    report.append("\n## 二、行业扫描\n")
    report.append(f"| 行业 | 股票数 |")
    report.append(f"|------|--------|")
    for ind in sorted(industry_stats.keys()):
        report.append(f"| {ind} | {industry_stats[ind]} |")
    report.append(f"| **合计** | **{sum(industry_stats.values())}** |")
    
    # 候选池
    report.append(f"\n## 三、候选标的池\n")
    report.append(f"筛选: PE {FILTER_PE_MIN}-{FILTER_PE_MAX} | ROE > {FILTER_ROE_MIN}%  |  共 **{len(candidates)}** 只\n")
    
    if candidates:
        report.append(f"| 代码 | 名称 | PE | ROE% | 价格 | 行业 | 营收增% | 利润增% |")
        report.append(f"|------|------|-----|------|------|------|---------|---------|")
        for c in candidates[:TOP_N]:
            pe_str = f"{c['pe']:.1f}" if c['pe'] else "-"
            price_str = f"{c['price']:.2f}" if c['price'] else "-"
            rev = f"{c['rev_growth']:.1f}" if c['rev_growth'] else "-"
            prof = f"{c['profit_growth']:.1f}" if c['profit_growth'] else "-"
            report.append(f"| {c['code']} | {c['name']} | {pe_str} | {c['roe']:.1f} | {price_str} | {c['industry']} | {rev} | {prof} |")
    
    # 下周关注
    report.append(f"\n## 四、下周关注\n")
    report.append("⏳ 待补充：政策事件、季报日历、解禁提醒")
    
    report.append(f"\n---\n*风险提示: 本报告由脚本自动生成，PE为年化估算，不构成投资建议。*")
    
    report_text = "\n".join(report)
    print("\n" + report_text)
    
    # 保存
    script_dir = os.path.dirname(os.path.abspath(__file__))
    reports_dir = os.path.join(script_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"week_{week_num}.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f"\n📄 报告已保存: {report_path}")

if __name__ == "__main__":
    main()
