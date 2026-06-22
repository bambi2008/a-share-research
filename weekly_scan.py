#!/usr/bin/env python3
"""
A股科技+新能源 周度扫描脚本
每周一运行，输出持仓体检 + 行业扫描 + 新标的池
"""

import subprocess
import json
import sys
from datetime import datetime, timedelta
from collections import defaultdict

# ── 配置 ────────────────────────────────────────────
HOLDINGS = {}  # 持仓：{代码: {成本价, 买入日期}}
# 示例格式：
# HOLDINGS = {
#     "600809": {"cost": 150.0, "date": "2026-06-15"},
#     "002027": {"cost": 10.5, "date": "2026-06-15"},
# }

FILTER_PE_MAX = 40          # PE(TTM) 上限
FILTER_PE_MIN = 3           # PE(TTM) 下限（排除异常低PE可能有问题）
FILTER_ROE_MIN = 5          # ROE 下限 (%)
FILTER_MV_MIN = 50          # 市值下限（亿）
FILTER_MV_MAX = 10000       # 市值上限（亿）

STOP_LOSS = -0.20           # 止损线 -20%
TAKE_PROFIT = 0.50          # 止盈线 +50%
EARNING_WARN = -0.20        # 季报利润下滑超20%警告

# ── 板块代码 ─────────────────────────────────────────
SECTORS = {
    "半导体材料": "BK1325",
    "电子化学品": "BK1039",
    "软件服务": "BK1447",
    "第三代半导体": "BK0952",
    "存储芯片": "BK1137",
    "AI概念": "BK1182",
    "云计算": "BK0579",
    "通信服务": "BK0736",
    "电池": "BK1033",
    "电池化学品": "BK1302",
    "光伏主材": "BK1318",
    "电网自动化": "BK1309",
    "锂电池": "BK0574",
    "固态电池": "BK0968",
    "特高压": "BK0918",
    "动力电池回收": "BK1052",
}


def fetch_json(url):
    """安全请求"""
    cmd = f'curl -sL "{url}" -H "User-Agent: Mozilla/5.0" -H "Referer: https://data.eastmoney.com/"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    try:
        return json.loads(r.stdout)
    except:
        return None


def safe_float(val):
    """安全转浮点"""
    try:
        return float(val) if val not in ('-', '', None) else None
    except:
        return None


def fetch_sector_stocks(bk_code):
    """拉取板块成分股"""
    url = (f'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500'
           f'&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:{bk_code}'
           f'&fields=f2,f3,f9,f12,f14,f20,f37,f115,f188,f186')
    data = fetch_json(url)
    if not data or not data.get('data') or not data['data'].get('diff'):
        return []
    return data['data']['diff']


def filter_quality(stocks):
    """按PE/ROE/市值筛选质量标的"""
    results = []
    for s in stocks:
        code = s.get('f12', '')
        name = s.get('f14', '')

        pe_ttm = safe_float(s.get('f115'))
        pe_dyn = safe_float(s.get('f9'))
        roe = safe_float(s.get('f37'))
        mv = safe_float(s.get('f20'))
        rev_g = safe_float(s.get('f188'))  # 营收同比
        profit_g = safe_float(s.get('f186'))  # 利润同比

        # 用 PE(TTM)，没有则用 PE(动态)
        pe = pe_ttm if pe_ttm and pe_ttm > 0 else (pe_dyn if pe_dyn and pe_dyn > 0 else None)

        if not pe or pe < FILTER_PE_MIN or pe > FILTER_PE_MAX:
            continue
        if not roe or roe < FILTER_ROE_MIN:
            continue
        if not mv or mv < FILTER_MV_MIN * 1e8 or mv > FILTER_MV_MAX * 1e8:
            continue

        results.append({
            'code': code,
            'name': name,
            'pe': pe,
            'roe': roe,
            'mv': mv / 1e8,
            'rev_growth': rev_g,
            'profit_growth': profit_g,
        })
    return results


def fetch_index_trend():
    """拉取大盘指数近期走势（创业板指 + 科创50）"""
    indices = {}
    for name, code, market in [("创业板指", "399006", "0"), ("科创50", "000688", "1"), ("上证指数", "000001", "1")]:
        url = (f'https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{code}'
               f'&fields=f43,f44,f45,f46,f48,f50,f57,f58,f169,f170')
        data = fetch_json(url)
        if data and data.get('data'):
            d = data['data']
            price = d.get('f43')
            chg_pct = d.get('f170')
            chg_amt = d.get('f169')
            indices[name] = {
                'price': price,
                'change_pct': chg_pct / 100 if chg_pct and abs(float(chg_pct)) > 50 else chg_pct,  # 可能以100为基数
                'change_amt': chg_amt,
            }
    return indices


def fetch_holdings_status():
    """持仓体检"""
    if not HOLDINGS:
        return []

    results = []
    for code, info in HOLDINGS.items():
        url = (f'https://push2.eastmoney.com/api/qt/stock/get?secid=0.{code}'
               f'&fields=f43,f57,f58,f170,f162,f167,f115,f188,f186')
        data = fetch_json(url)
        if not data or not data.get('data'):
            continue

        d = data['data']
        current_price = safe_float(d.get('f43'))
        pe = safe_float(d.get('f115')) or safe_float(d.get('f162'))
        profit_g = safe_float(d.get('f186'))

        if current_price:
            cost = info.get('cost', 0)
            pnl_pct = (current_price / 100 - cost) / cost * 100 if cost else None  # price in fen
            price_yuan = current_price / 100
        else:
            pnl_pct = None
            price_yuan = None

        alerts = []
        if pnl_pct is not None:
            if pnl_pct <= STOP_LOSS * 100:
                alerts.append(f'🔴 触及止损线 ({pnl_pct:.1f}%)')
            if pnl_pct >= TAKE_PROFIT * 100:
                alerts.append(f'🟢 触及止盈线 ({pnl_pct:.1f}%)')
        if profit_g is not None and profit_g < EARNING_WARN * 100:
            alerts.append(f'⚠️ 利润同比下滑 {profit_g:.1f}%')

        results.append({
            'code': code,
            'name': d.get('f58', ''),
            'price': price_yuan,
            'cost': info.get('cost'),
            'pnl_pct': pnl_pct,
            'pe': pe,
            'profit_growth': profit_g,
            'alerts': alerts,
        })
    return results


def generate_report(holdings_status, all_candidates, indices):
    """生成周报"""
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=4)

    report = []
    report.append("=" * 60)
    report.append(f"  A股科技+新能源 周度扫描报告")
    report.append(f"  {week_start.strftime('%Y.%m.%d')} - {week_end.strftime('%Y.%m.%d')}")
    report.append(f"  生成时间: {now.strftime('%Y-%m-%d %H:%M')}")
    report.append("=" * 60)

    # ── 一、大盘概况 ──
    report.append("\n## 一、大盘概况\n")
    for name, info in indices.items():
        chg = info.get('change_pct')
        chg_str = f"{chg:+.2f}%" if chg else '-'
        price = info.get('price')
        price_str = f"{price/100:.2f}" if price else '-'
        report.append(f"  {name}: {price_str} 周涨跌: {chg_str}")

    # ── 二、持仓体检 ──
    report.append("\n## 二、持仓体检\n")
    if not holdings_status:
        report.append("  ⚠️ 未配置持仓，请在脚本 HOLDINGS 字典中设置")
        report.append("  格式: HOLDINGS = {\"600809\": {\"cost\": 150.0, \"date\": \"2026-06-15\"}}")
    else:
        for h in holdings_status:
            pnl = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] else '-'
            pe_str = f"PE={h['pe']:.1f}" if h['pe'] else ''
            report.append(f"  {h['code']} {h['name']}")
            report.append(f"    现价: {h['price']}  成本: {h['cost']}  盈亏: {pnl}  {pe_str}")
            for alert in h['alerts']:
                report.append(f"    {alert}")

    # ── 三、行业扫描 ──
    report.append("\n## 三、候选标的池\n")
    report.append(f"  筛选条件: PE {FILTER_PE_MIN}-{FILTER_PE_MAX} | ROE > {FILTER_ROE_MIN}% | 市值 {FILTER_MV_MIN}-{FILTER_MV_MAX}亿")
    report.append(f"  候选总数: {len(all_candidates)}\n")

    if not all_candidates:
        report.append("  当前无符合条件的标的")
    else:
        # 按 ROE 排序
        sorted_candidates = sorted(all_candidates, key=lambda x: x['roe'], reverse=True)
        report.append(f"  {'代码':<8} {'名称':<10} {'PE':<6} {'ROE%':<8} {'市值亿':<8} {'营收增%':<10} {'利润增%'}")
        report.append("  " + "-" * 54)
        for c in sorted_candidates:
            rev = f"{c['rev_growth']:.1f}" if c['rev_growth'] else '-'
            prof = f"{c['profit_growth']:.1f}" if c['profit_growth'] else '-'
            report.append(f"  {c['code']:<8} {c['name']:<10} {c['pe']:<6.1f} {c['roe']:<8.1f} {c['mv']:<8.0f} {rev:<10} {prof}")

    # ── 四、下周关注 ──
    report.append("\n## 四、下周关注\n")
    report.append("  ⏳ 待补充：政策事件、季报日历、解禁提醒")

    report.append("\n" + "=" * 60)
    report.append("  风险提示: 本报告由脚本自动生成，不构成投资建议")
    report.append("=" * 60)

    return "\n".join(report)


def main():
    print("🔍 开始扫描科技+新能源板块...")

    # 1. 拉取大盘指数
    print("  1/4 大盘指数...")
    indices = fetch_index_trend()

    # 2. 拉取各板块并合并去重
    print("  2/4 板块成分股...")
    all_stocks = {}
    for sector_name, bk_code in SECTORS.items():
        stocks = fetch_sector_stocks(bk_code)
        for s in stocks:
            code = s.get('f12', '')
            if code not in all_stocks:
                all_stocks[code] = s
    print(f"      覆盖 {len(SECTORS)} 个板块, {len(all_stocks)} 只个股（去重后）")

    # 3. 质量筛选
    print("  3/4 质量筛选...")
    candidates = filter_quality(list(all_stocks.values()))
    print(f"      符合条件: {len(candidates)} 只")

    # 4. 持仓体检
    print("  4/4 持仓体检...")
    holdings_status = fetch_holdings_status()

    # 5. 生成报告
    report = generate_report(holdings_status, candidates, indices)
    print("\n" + report)

    # 保存到文件
    week_num = datetime.now().isocalendar()[1]
    import os
    os.makedirs("/Users/mao18/Projects/a-share-research/reports", exist_ok=True)
    report_path = f"/Users/mao18/Projects/a-share-research/reports/week_{week_num}.md"
    with open(report_path, 'w') as f:
        f.write(report)
    print(f"\n📄 报告已保存: {report_path}")


if __name__ == "__main__":
    main()
