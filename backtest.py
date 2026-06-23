#!/usr/bin/env python3
"""
策略历史回测模块
逻辑: 在历史某报告期披露后用相同策略(行业+ROE+PE)选股，
      等权持有 N 个月，对比组合收益 vs 大盘指数。

数据源: 巨潮(历史财报) + 新浪(历史日线)
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import scanner


def _sina_symbol(code):
    if code.startswith(('60', '68', '90', '11', '51')):
        return f"sh{code}"
    elif code.startswith(('00', '30', '12', '15', '20')):
        return f"sz{code}"
    elif code.startswith(('8', '4', '92')):
        return f"bj{code}"
    return f"sh{code}"


def _price_on_or_after(code, date_str, window_days=15):
    """取 date_str 当日或之后最近一个交易日的收盘价(前复权)"""
    start = date_str
    end = (datetime.strptime(date_str, "%Y%m%d") + timedelta(days=window_days)).strftime("%Y%m%d")
    try:
        df = scanner._fetch_with_timeout(
            ak.stock_zh_a_daily, 25,
            symbol=_sina_symbol(code), start_date=start, end_date=end, adjust="qfq"
        )
        if df is not None and len(df) > 0:
            return float(df.iloc[0]['close'])
    except Exception:
        pass
    return None


def run_backtest(report_date, hold_months=6, top_n=20, progress_callback=None):
    """
    report_date: 财报报告期 'YYYYMMDD' (如 '20250331')
    hold_months: 持有月数
    top_n: 取 ROE 最高的前 N 只回测
    """
    def log(m):
        if progress_callback:
            progress_callback(m)
        else:
            print(f"  {m}")

    # 建仓日 = 报告期 + 约30天(财报披露后)；平仓日 = 建仓 + hold_months
    rd = datetime.strptime(report_date, "%Y%m%d")
    entry_date = (rd + timedelta(days=35)).strftime("%Y%m%d")
    exit_date = (rd + timedelta(days=35 + hold_months * 30)).strftime("%Y%m%d")

    log(f"报告期={report_date} 建仓≈{entry_date} 平仓≈{exit_date} 持有{hold_months}月")

    # 1. 历史财报
    log(f"获取 {report_date} 财报...")
    df_q = scanner._fetch_with_timeout(ak.stock_yjbb_em, scanner.FETCH_TIMEOUT, date=report_date)
    log(f"  全A {len(df_q)} 只")

    # 2. 行业 + ROE 筛选
    picks = []
    for _, row in df_q.iterrows():
        industry = str(row.get('所处行业', ''))
        if industry not in scanner.TARGET_INDUSTRIES:
            continue
        roe = row.get('净资产收益率')
        if pd.isna(roe) or roe < scanner.FILTER_ROE_MIN:
            continue
        picks.append({'code': str(row['股票代码']), 'name': str(row['股票简称']),
                      'roe': roe, 'industry': industry})
    picks.sort(key=lambda x: x['roe'], reverse=True)
    picks = picks[:top_n]
    log(f"  筛选+TopROE: {len(picks)} 只")

    # 3. 逐只取建仓/平仓价
    log(f"计算 {len(picks)} 只个股收益...")
    returns = []
    valid_picks = []
    for i, p in enumerate(picks):
        entry_p = _price_on_or_after(p['code'], entry_date)
        exit_p = _price_on_or_after(p['code'], exit_date)
        if entry_p and exit_p and entry_p > 0:
            ret = (exit_p - entry_p) / entry_p * 100
            p['entry'] = entry_p
            p['exit'] = exit_p
            p['return'] = ret
            returns.append(ret)
            valid_picks.append(p)
        if (i + 1) % 5 == 0:
            log(f"  进度 {i+1}/{len(picks)}")

    if not returns:
        log("⚠️ 无有效收益数据(可能历史区间数据缺失)")
        return None

    # 4. 组合等权收益
    portfolio_return = sum(returns) / len(returns)

    # 5. 基准: 创业板指
    bench_return = None
    try:
        df_idx = scanner._fetch_with_timeout(ak.stock_zh_index_daily, 30, symbol="sz399006")
        df_idx['date'] = pd.to_datetime(df_idx['date'])
        entry_dt = pd.to_datetime(entry_date)
        exit_dt = pd.to_datetime(exit_date)
        entry_rows = df_idx[df_idx['date'] >= entry_dt]
        exit_rows = df_idx[df_idx['date'] >= exit_dt]
        if len(entry_rows) and len(exit_rows):
            ep = entry_rows.iloc[0]['close']
            xp = exit_rows.iloc[0]['close']
            bench_return = (xp - ep) / ep * 100
    except Exception:
        pass

    # 胜率
    win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100
    excess = (portfolio_return - bench_return) if bench_return is not None else None

    valid_picks.sort(key=lambda x: x['return'], reverse=True)

    result = {
        "report_date": report_date,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "hold_months": hold_months,
        "n_stocks": len(valid_picks),
        "portfolio_return": portfolio_return,
        "bench_return": bench_return,
        "excess_return": excess,
        "win_rate": win_rate,
        "best": valid_picks[0] if valid_picks else None,
        "worst": valid_picks[-1] if valid_picks else None,
        "picks": valid_picks,
    }
    return result


def build_backtest_report(result):
    if result is None:
        return "回测失败：无有效数据"
    r = []
    r.append("=" * 60)
    r.append("  策略历史回测报告")
    r.append("=" * 60)
    r.append(f"\n报告期: {result['report_date']}  |  持有: {result['hold_months']}个月")
    r.append(f"建仓≈{result['entry_date']}  平仓≈{result['exit_date']}")
    r.append(f"组合股数: {result['n_stocks']} 只(等权)")
    r.append(f"\n## 收益对比\n")
    pr = result['portfolio_return']
    br = result['bench_return']
    r.append(f"| 指标 | 数值 |")
    r.append(f"|------|------|")
    r.append(f"| 策略组合收益 | {pr:+.2f}% |")
    r.append(f"| 创业板指收益 | {br:+.2f}% |" if br is not None else "| 创业板指收益 | 数据缺失 |")
    if result['excess_return'] is not None:
        ex = result['excess_return']
        verdict = "✅ 跑赢" if ex > 0 else "❌ 跑输"
        r.append(f"| 超额收益 | {ex:+.2f}% {verdict} |")
    r.append(f"| 胜率 | {result['win_rate']:.0f}% |")

    if result['best']:
        b = result['best']
        r.append(f"\n最佳: {b['code']} {b['name']} {b['return']:+.1f}% ({b['industry']})")
    if result['worst']:
        w = result['worst']
        r.append(f"最差: {w['code']} {w['name']} {w['return']:+.1f}% ({w['industry']})")

    r.append(f"\n## 个股明细\n")
    r.append("| 代码 | 名称 | 建仓价 | 平仓价 | 收益% | 行业 |")
    r.append("|------|------|--------|--------|-------|------|")
    for p in result['picks']:
        r.append(f"| {p['code']} | {p['name']} | {p['entry']:.2f} | {p['exit']:.2f} | {p['return']:+.1f} | {p['industry']} |")

    r.append(f"\n---\n*回测基于历史数据，不代表未来表现。已用前复权价格。*")
    return "\n".join(r)


if __name__ == "__main__":
    import sys
    # 默认回测 2025Q1 财报，持有6个月
    rd = sys.argv[1] if len(sys.argv) > 1 else "20250331"
    months = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    print(f"🔬 回测: 报告期={rd}, 持有{months}月\n")
    result = run_backtest(rd, hold_months=months, top_n=20)
    print("\n" + build_backtest_report(result))
