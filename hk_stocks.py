#!/usr/bin/env python3
"""
港股核心标的跟踪模块
数据源: 新浪(通过 akshare stock_hk_spot_em)
"""
import akshare as ak

# 重点关注的港股标的
WATCHLIST = [
    # AI制药
    ("晶泰控股", "02228", "AI制药"),
    ("英矽智能", "02252", "AI制药"),
    ("剂泰科技", "02257", "AI制药"),
    # 互联网平台
    ("腾讯控股", "00700", "互联网"),
    ("快手", "01024", "短视频"),
    ("美团", "03690", "本地生活"),
    # 新能源车
    ("小米集团", "01810", "人车家"),
    ("小鹏汽车", "09868", "智能驾驶"),
    ("理想汽车", "02015", "增程EV"),
    # AI芯片/机器人
    ("地平线机器人", "09660", "智驾芯片"),
    ("优必选", "09880", "人形机器人"),
    # 消费品牌
    ("泡泡玛特", "09992", "IP消费"),
    ("蜜雪集团", "02097", "饮品"),
    # 建筑科技
    ("万物云", "02602", "空间科技"),
    ("明源云", "00909", "地产SaaS"),
]


def fetch_hk_watchlist(timeout=60):
    """获取港股关注列表实时数据。主源:新浪 stock_hk_spot → 备用:东财 stock_hk_spot_em"""
    df = None
    # 主源: 新浪(Windows兼容)
    try:
        df = ak.stock_hk_spot()
    except Exception:
        pass
    # 备用: 东财
    if df is None:
        try:
            df = ak.stock_hk_spot_em()
        except Exception as e:
            return [], f"港股数据获取失败(所有源): {e}"

    results = []
    for name, code, sector in WATCHLIST:
        row = df[df['代码'] == code]
        if not row.empty:
            r = row.iloc[0]
            results.append({
                "name": name,
                "code": code,
                "sector": sector,
                "price": r.get("最新价"),
                "chg_pct": r.get("涨跌幅"),
                "volume": r.get("成交量"),
                "amount": r.get("成交额"),
            })
        else:
            results.append({
                "name": name, "code": code, "sector": sector,
                "price": None, "chg_pct": None, "volume": None, "amount": None,
            })
    return results, None


def build_hk_report(results):
    """生成港股监控报告"""
    lines = [
        "=" * 56,
        "  港股核心标的监控",
        f"  共 {len(results)} 只",
        "=" * 56,
        "",
        "| 代码 | 名称 | 行业 | 最新价 | 涨跌幅 |",
        "|------|------|------|--------|--------|",
    ]
    for r in results:
        price_str = f"{r['price']:.2f}" if r['price'] else "-"
        chg_str = f"{r['chg_pct']:+.2f}%" if r['chg_pct'] is not None else "-"
        lines.append(f"| {r['code']} | {r['name']} | {r['sector']} | {price_str} | {chg_str} |")
    return "\n".join(lines)
