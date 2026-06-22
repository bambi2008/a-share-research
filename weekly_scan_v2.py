#!/usr/bin/env python3
"""
A股科技+新能源 周度扫描 v2
数据源: 巨潮资讯(juchao) + 新浪(sina) — 绕过 Windows 东方财富 TLS 问题
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import os, sys

# ── 配置 ──
HOLDINGS = {}
FILTER_PE_MIN, FILTER_PE_MAX = 3, 40
FILTER_ROE_MIN = 5
STOP_LOSS, TAKE_PROFIT = -0.20, 0.50

# 科技+新能源行业关键词（匹配巨潮"所处行业"字段）
TARGET_INDUSTRIES = [
    "半导体", "电子化学品", "软件", "IT", "计算机", "通信",
    "互联网", "云计算", "人工智能", "大数据", "芯片", "存储",
    "电池", "光伏", "太阳能", "风电", "电网", "电力设备",
    "新能源", "锂电", "固态电池", "特高压", "充电桩", "储能",
    "电器", "电子", "光学", "光电子", "自动化", "机器人",
]

def match_industry(industry_str):
    """检查行业是否属于科技+新能源"""
    if pd.isna(industry_str):
        return False
    industry_str = str(industry_str)
    return any(kw in industry_str for kw in TARGET_INDUSTRIES)

def main():
    print("🔍 A股科技+新能源 周度扫描 v2 (巨潮+新浪)")
    
    # ── 1. 大盘指数（新浪） ──
    print("  1/5 大盘指数(新浪)...")
    indices = {}
    try:
        df_idx = ak.stock_zh_index_daily_em(symbol="sz399006")  # 创业板指
        if len(df_idx) > 0:
            latest = df_idx.iloc[-1]
            print(f"  创业板指: {latest['close']} (最近交易日)")
    except Exception as e:
        print(f"  创业板指: 跳过 ({type(e).__name__})")
    
    # ── 2. 全A季度财报（巨潮） ──
    print("  2/5 季度财报(巨潮)...")
    try:
        df_q = ak.stock_yjbb_em(date="20260331")
        print(f"  获取 {len(df_q)} 只股票季报")
    except Exception as e:
        print(f"  ❌ 巨潮数据获取失败: {e}")
        return
    
    # ── 3. 实时价格（新浪） ──
    print("  3/5 实时行情(新浪)...")
    try:
        df_price = ak.stock_zh_a_spot()
        price_map = {}
        for _, row in df_price.iterrows():
            code = str(row['代码']).replace('bj','').replace('sh','').replace('sz','')
            price_map[code] = row['最新价']
        print(f"  获取 {len(price_map)} 只股票价格")
    except Exception as e:
        print(f"  ❌ 新浪行情失败: {e}")
        price_map = {}
    
    # ── 4. 筛选 ──
    print("  4/5 行业+ROE+PE筛选...")
    candidates = []
    for _, row in df_q.iterrows():
        code = str(row['股票代码'])
        name = str(row['股票简称'])
        industry = row.get('所处行业', '')
        
        # 行业匹配
        if not match_industry(industry):
            continue
        
        # ROE
        roe = row.get('净资产收益率')
        if pd.isna(roe) or roe < FILTER_ROE_MIN:
            continue
        
        # PE计算: 价格 / (每股收益 × 4)
        eps = row.get('每股收益')
        price = price_map.get(code)
        if pd.isna(eps) or eps <= 0 or not price:
            pe = None
        else:
            pe = price / (eps * 4)
        
        if pe and (pe < FILTER_PE_MIN or pe > FILTER_PE_MAX):
            continue
        
        rev_g = row.get('营业总收入-同比增长')
        profit_g = row.get('净利润-同比增长')
        
        candidates.append({
            'code': code, 'name': name, 'pe': pe, 'roe': roe,
            'eps': eps, 'price': price, 'industry': industry,
            'rev_growth': rev_g if not pd.isna(rev_g) else None,
            'profit_growth': profit_g if not pd.isna(profit_g) else None,
        })
    
    candidates.sort(key=lambda x: x['roe'] or 0, reverse=True)
    print(f"  行业匹配+筛选后: {len(candidates)} 只")
    
    # ── 5. 生成报告 ──
    print("  5/5 生成报告...")
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=4)
    
    report = []
    report.append("=" * 60)
    report.append(f"  A股科技+新能源 周度扫描报告 v2")
    report.append(f"  {week_start.strftime('%Y.%m.%d')} - {week_end.strftime('%Y.%m.%d')}")
    report.append(f"  生成时间: {now.strftime('%Y-%m-%d %H:%M')}")
    report.append(f"  数据源: 巨潮资讯 + 新浪财经")
    report.append("=" * 60)
    
    report.append(f"\n## 一、扫描概况\n")
    report.append(f"  全A季报: {len(df_q)} 只")
    report.append(f"  科技+新能源行业匹配: 已筛选")
    report.append(f"  筛选条件: PE {FILTER_PE_MIN}-{FILTER_PE_MAX} | ROE > {FILTER_ROE_MIN}%")
    report.append(f"  候选总数: {len(candidates)} 只\n")
    
    if candidates:
        report.append(f"  {'代码':<8} {'名称':<10} {'PE':<8} {'ROE%':<8} {'价格':<8} {'行业'}")
        report.append("  " + "-" * 60)
        for c in candidates[:30]:
            pe_str = f"{c['pe']:.1f}" if c['pe'] else '-'
            price_str = f"{c['price']:.2f}" if c['price'] else '-'
            report.append(f"  {c['code']:<8} {c['name']:<10} {pe_str:<8} {c['roe']:<8.1f} {price_str:<8} {c['industry']}")
    else:
        report.append("  当前无符合条件的标的")
    
    report.append("\n## 二、持仓体检\n")
    if not HOLDINGS:
        report.append("  ⚠️ 未配置持仓")
    else:
        report.append("  (待实现)")
    
    report.append("\n## 三、下周关注\n")
    report.append("  ⏳ 待补充：政策事件、季报日历、解禁提醒")
    
    report.append("\n" + "=" * 60)
    report.append("  风险提示: 本报告由脚本自动生成，不构成投资建议")
    report.append("=" * 60)
    
    report_text = "\n".join(report)
    print("\n" + report_text)
    
    # 保存
    week_num = now.isocalendar()[1]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    reports_dir = os.path.join(script_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"week_{week_num}.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f"\n📄 报告已保存: {report_path}")

if __name__ == "__main__":
    main()
