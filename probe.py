#!/usr/bin/env python3
"""
网络探测脚本 probe.py
=====================
逐个测试各数据源在当前网络下能否连通、耗时多少, 每项独立、带超时保护,
一项卡住不影响下一项。跑法: py -3.12 probe.py
"""
import concurrent.futures
import time


def timed(label, fn, timeout=40):
    """在子线程跑 fn, 超时/报错都如实打印, 不阻塞后续。"""
    print(f"\n[{label}] 测试中(最多等 {timeout}s)...")
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn)
    t = time.time()
    try:
        result = fut.result(timeout=timeout)
        print(f"  ✓ 成功  用时 {time.time()-t:.1f}s  →  {result}")
    except concurrent.futures.TimeoutError:
        print(f"  ✗ 超时(>{timeout}s) —— 此源在你网络下不可用")
    except Exception as e:
        print(f"  ✗ 报错: {type(e).__name__}: {str(e)[:100]}")
    finally:
        ex.shutdown(wait=False)


# ── 1. baostock 个股收盘(单只, 轻量) ──
def bs_single():
    import baostock as bs
    bs.login()
    try:
        rs = bs.query_history_k_data_plus(
            "sh.600519", "date,close",
            start_date="2026-06-20", end_date="2026-06-30", frequency="d")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return f"茅台最近收盘 {rows[-1] if rows else '无数据'}"
    finally:
        bs.logout()


# ── 2. baostock 沪深300成分(约300只, 中等) ──
def bs_hs300():
    import baostock as bs
    bs.login()
    try:
        rs = bs.query_hs300_stocks()
        n = 0
        while rs.next():
            n += 1
        return f"沪深300成分 {n} 只"
    finally:
        bs.logout()


# ── 3. baostock 全市场列表(约5000只, 重) ──
def bs_all():
    import baostock as bs
    bs.login()
    try:
        rs = bs.query_all_stock(day="2026-06-30")
        n = 0
        while rs.next():
            n += 1
        return f"全市场 {n} 只"
    finally:
        bs.logout()


# ── 4. 新浪单只实时价(轻量, 看新浪小接口通不通) ──
def sina_single():
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol="sh000001")
    return f"上证指数最新 {df.iloc[-1]['close']}"


if __name__ == "__main__":
    print("=" * 50)
    print("数据源连通性探测(在你当前网络下)")
    print("=" * 50)
    timed("1. baostock 个股收盘", bs_single, timeout=30)
    timed("2. baostock 沪深300", bs_hs300, timeout=40)
    timed("3. baostock 全市场", bs_all, timeout=60)
    timed("4. 新浪指数(小接口)", sina_single, timeout=30)
    print("\n" + "=" * 50)
    print("探测完成。把上面每项的 ✓/✗ 结果贴回去。")
    print("=" * 50)
