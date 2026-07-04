#!/usr/bin/env python3
"""
高管增减持监控 — 扫描董监高持股变动，标记抛售信号
数据源: 上交所(stock_share_hold_change_sse) + 深交所(stock_share_hold_change_szse)
每个源15秒硬超时，并行获取。
"""
import concurrent.futures


def _fetch_sse():
    import akshare as ak
    return ak.stock_share_hold_change_sse(symbol="全部")


def _fetch_szse():
    import akshare as ak
    return ak.stock_share_hold_change_szse(symbol="全部")


def fetch_insider_changes(progress_callback=None):
    """获取沪深两市董监高持股变动。并行+超时。
    返回: {code: {name, sell_count, buy_count, sell_ratio, alert}}
    """
    def log(msg):
        if progress_callback:
            progress_callback(msg)

    sse_data = []
    szse_data = []

    log("高管增减持: 沪深并行...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f_sse = pool.submit(_fetch_sse)
        f_szse = pool.submit(_fetch_szse)

        try:
            sse_data = f_sse.result(timeout=15)
            log(f"  上交所: {len(sse_data)} 条变动")
        except concurrent.futures.TimeoutError:
            log("  上交所: 超时跳过")
        except Exception as e:
            log(f"  上交所跳过: {e}")

        try:
            szse_data = f_szse.result(timeout=15)
            log(f"  深交所: {len(szse_data)} 条变动")
        except concurrent.futures.TimeoutError:
            log("  深交所: 超时跳过")
        except Exception as e:
            log(f"  深交所跳过: {e}")

    if not sse_data and not szse_data:
        log("  高管增减持: 两市均无数据")
        return {}

    # 合并分析
    code_stats = {}
    all_data = list(sse_data)
    all_data.extend(szse_data)

    for row in all_data:
        try:
            code = str(row.get("公司代码", row.get("证券代码", "")))
            if not code or len(code) < 6:
                continue
            code = code[:6]
            name = row.get("公司名称", row.get("证券简称", ""))
            change = row.get("变动数", row.get("变动数量", 0))
            try:
                change = float(change)
            except (ValueError, TypeError):
                continue

            if code not in code_stats:
                code_stats[code] = {"name": name, "sell": 0, "buy": 0}

            if change < 0:
                code_stats[code]["sell"] += abs(change)
            else:
                code_stats[code]["buy"] += change
        except Exception:
            continue

    # 生成告警
    alerts = {}
    for code, stats in code_stats.items():
        total = stats["sell"] + stats["buy"]
        if total == 0:
            continue
        sell_ratio = stats["sell"] / total

        alert_level = None
        if sell_ratio > 0.8 and stats["sell"] > 0:
            alert_level = "red"
        elif sell_ratio > 0.5:
            alert_level = "yellow"

        if alert_level:
            alerts[code] = {
                "name": stats["name"],
                "sell_shares": int(stats["sell"]),
                "buy_shares": int(stats["buy"]),
                "sell_ratio": round(sell_ratio * 100),
                "alert": alert_level,
            }

    red_count = sum(1 for a in alerts.values() if a["alert"] == "red")
    yellow_count = sum(1 for a in alerts.values() if a["alert"] == "yellow")
    log(f"  高管减持告警: {red_count} 红 / {yellow_count} 黄 (共 {len(alerts)} 只)")

    return alerts


def check_stock(code, insider_alerts):
    if not insider_alerts:
        return False, None, ""
    info = insider_alerts.get(code)
    if not info:
        return False, None, ""
    level = info["alert"]
    detail = f"高管{level}告警(卖{info['sell_shares']}股/卖比{info['sell_ratio']}%)"
    return True, level, detail
