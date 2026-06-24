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

# 交易成本(单边): 佣金万2.5 + 印花税千1(卖出) + 滑点千1 ≈ 双边约0.35%
TXN_COST_PCT = 0.35  # 双边总成本(%)


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
            ret = (exit_p - entry_p) / entry_p * 100 - TXN_COST_PCT  # 扣除双边交易成本
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

    r.append(f"\n---\n*回测基于历史数据，不代表未来表现。已用前复权价格，已扣除约{TXN_COST_PCT}%双边交易成本。*")
    return "\n".join(r)


def run_rolling_backtest(report_dates, hold_months=6, top_n=20, progress_callback=None):
    """多期滚动回测。
    report_dates: 报告期列表，如 ['20240331','20240630','20240930','20241231','20250331']
    对每期跑单期回测，汇总组合收益序列，算夏普/最大回撤/累计收益。
    """
    def log(m):
        if progress_callback:
            progress_callback(m)
        else:
            print(f"  {m}")

    periods = []
    for i, rd in enumerate(report_dates, 1):
        log(f"[{i}/{len(report_dates)}] 回测报告期 {rd}...")
        try:
            res = run_backtest(rd, hold_months=hold_months, top_n=top_n,
                               progress_callback=lambda m: None)
            if res:
                periods.append(res)
                log(f"  {rd}: 组合{res['portfolio_return']:+.1f}% 基准"
                    f"{res['bench_return']:+.1f}% 超额"
                    f"{(res['excess_return'] or 0):+.1f}%" if res['bench_return'] is not None
                    else f"  {rd}: 组合{res['portfolio_return']:+.1f}%")
        except Exception as e:
            log(f"  {rd}: 失败 {type(e).__name__}")

    if not periods:
        return None

    # 汇总统计
    port_returns = [p['portfolio_return'] for p in periods]
    bench_returns = [p['bench_return'] for p in periods if p['bench_return'] is not None]
    excess_returns = [p['excess_return'] for p in periods if p['excess_return'] is not None]

    n = len(port_returns)
    avg_return = sum(port_returns) / n
    win_periods = sum(1 for r in port_returns if r > 0)
    beat_bench = sum(1 for p in periods if p['excess_return'] is not None and p['excess_return'] > 0)

    # 夏普比率(按期收益，年化需考虑持有期)。这里用简单期间夏普: mean/std
    import statistics
    std = statistics.pstdev(port_returns) if n > 1 else 0
    sharpe = (avg_return / std) if std > 0 else None
    # 年化夏普(假设每持有期=hold_months, 一年期数=12/hold_months)
    periods_per_year = 12 / hold_months
    sharpe_annual = (sharpe * (periods_per_year ** 0.5)) if sharpe is not None else None

    # 最大回撤(基于累计净值序列)
    nav = 1.0
    navs = [nav]
    for r in port_returns:
        nav *= (1 + r / 100)
        navs.append(nav)
    peak = navs[0]
    max_dd = 0
    for v in navs:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100
        max_dd = max(max_dd, dd)

    cum_return = (navs[-1] - 1) * 100

    # ── 专业风险指标 ──
    # Sortino: 下行标准差(只算负收益)
    neg_returns = [r for r in port_returns if r < 0]
    if neg_returns:
        down_std = statistics.pstdev(neg_returns) if len(neg_returns) > 1 else statistics.pstdev(neg_returns + [0])
        sortino = (avg_return / down_std) if down_std > 0 else None
        sortino_annual = (sortino * (periods_per_year ** 0.5)) if sortino is not None else None
    else:
        sortino = sortino_annual = None  # 无下行期，Sortino无穷大

    # Calmar: 年化收益 / 最大回撤
    if max_dd > 0:
        annual_return = ((1 + cum_return/100) ** (1/(n * hold_months/12)) - 1) * 100
        calmar = annual_return / max_dd
    else:
        calmar = None

    # Beta & Alpha vs 基准
    beta = alpha = info_ratio = None
    if len(bench_returns) == n:
        # 用最小二乘: port_return = alpha + beta * bench_return
        avg_bench = sum(bench_returns) / len(bench_returns)
        covar = sum((pr - avg_return) * (br - avg_bench) for pr, br in zip(port_returns, bench_returns)) / n
        bench_var = sum((br - avg_bench)**2 for br in bench_returns) / n
        if bench_var > 0:
            beta = covar / bench_var
            alpha = avg_return - beta * avg_bench
            # Alpha年化
            alpha_annual = alpha * periods_per_year
            # Information Ratio: 平均超额 / 超额标准差
            excess_std = statistics.pstdev(excess_returns) if len(excess_returns) > 1 else 0
            info_ratio = (avg_return - avg_bench) / excess_std if excess_std > 0 else None
            info_annual = (info_ratio * (periods_per_year ** 0.5)) if info_ratio is not None else None

    return {
        "periods": periods,
        "n_periods": n,
        "avg_return": avg_return,
        "cum_return": cum_return,
        "win_periods": win_periods,
        "beat_bench": beat_bench,
        "avg_excess": (sum(excess_returns) / len(excess_returns)) if excess_returns else None,
        "sharpe": sharpe,
        "sharpe_annual": sharpe_annual,
        "sortino": sortino,
        "sortino_annual": sortino_annual,
        "calmar": calmar,
        "beta": beta,
        "alpha": alpha,
        "alpha_annual": alpha_annual if beta is not None else None,
        "info_ratio": info_ratio,
        "info_annual": info_annual if beta is not None else None,
        "max_drawdown": max_dd,
        "hold_months": hold_months,
        "top_n": top_n,
    }


def build_rolling_report(result):
    if result is None:
        return "多期回测失败：无有效数据"
    r = []
    r.append("=" * 64)
    r.append("  策略多期滚动回测报告")
    r.append("=" * 64)
    r.append(f"\n回测期数: {result['n_periods']} 期  |  每期持有: {result['hold_months']}个月  |  每期选股: {result['top_n']}只")

    r.append(f"\n## 核心指标\n")
    r.append("| 指标 | 数值 |")
    r.append("|------|------|")
    r.append(f"| 累计收益(复利) | {result['cum_return']:+.1f}% |")
    r.append(f"| 平均每期收益 | {result['avg_return']:+.2f}% |")
    if result['avg_excess'] is not None:
        r.append(f"| 平均超额收益 | {result['avg_excess']:+.2f}% |")
    r.append(f"| 盈利期数 | {result['win_periods']}/{result['n_periods']} |")
    r.append(f"| 跑赢基准期数 | {result['beat_bench']}/{result['n_periods']} |")
    if result['sharpe'] is not None:
        r.append(f"| 年化夏普比率 | {result['sharpe_annual']:.2f} |")
    if result.get('sortino_annual') is not None:
        r.append(f"| 年化索提诺比率 | {result['sortino_annual']:.2f} (仅负收益波动) |")
    if result.get('calmar') is not None:
        r.append(f"| 卡尔玛比率 | {result['calmar']:.2f} (年化收益/最大回撤) |")
    if result.get('beta') is not None:
        r.append(f"| Beta | {result['beta']:.2f} |")
    if result.get('alpha_annual') is not None:
        r.append(f"| 年化Alpha | {result['alpha_annual']:+.2f}%/年 |")
    if result.get('info_annual') is not None:
        r.append(f"| 年化信息比率 | {result['info_annual']:.2f} |")
    r.append(f"| 最大回撤 | -{result['max_drawdown']:.1f}% |")

    # 夏普评价
    sa = result['sharpe_annual']
    if sa is not None:
        if sa >= 1.5:
            sj = "优秀(≥1.5)"
        elif sa >= 1.0:
            sj = "良好(1.0-1.5)"
        elif sa >= 0.5:
            sj = "一般(0.5-1.0)"
        else:
            sj = "较弱(<0.5)"
        r.append(f"\n> 年化夏普 {sa:.2f} — {sj}")

    r.append(f"\n## 各期明细\n")
    r.append("| 报告期 | 建仓 | 平仓 | 组合% | 基准% | 超额% | 胜率 |")
    r.append("|--------|------|------|-------|-------|-------|------|")
    for p in result['periods']:
        br = f"{p['bench_return']:+.1f}" if p['bench_return'] is not None else "-"
        ex = f"{p['excess_return']:+.1f}" if p['excess_return'] is not None else "-"
        r.append(f"| {p['report_date']} | {p['entry_date']} | {p['exit_date']} | "
                 f"{p['portfolio_return']:+.1f} | {br} | {ex} | {p['win_rate']:.0f}% |")

    r.append(f"\n---")
    r.append(f"*多期回测已扣除约{TXN_COST_PCT}%双边交易成本，使用前复权价格。*")
    r.append(f"*夏普比率基于期间收益估算，假设无风险利率为0。回测不代表未来表现。*")
    return "\n".join(r)


if __name__ == "__main__":
    import sys
    # 默认回测 2025Q1 财报，持有6个月
    rd = sys.argv[1] if len(sys.argv) > 1 else "20250331"
    months = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    print(f"🔬 回测: 报告期={rd}, 持有{months}月\n")
    result = run_backtest(rd, hold_months=months, top_n=20)
    print("\n" + build_backtest_report(result))
