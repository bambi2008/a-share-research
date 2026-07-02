#!/usr/bin/env python3
"""
并发能力探测 probe_concurrency.py
=================================
你的网络"单只能通、批量就堵"。本脚本测试: 用不同并发数拉一批个股收盘,
看哪个并发档位又快又稳(成功率高), 为并发版 data_source 定参数。
跑法: py -3.12 probe_concurrency.py
"""
import concurrent.futures
import time

# 20 只测试标的(覆盖沪深、大中小盘)
TEST_CODES = [
    "sh.600519", "sh.600036", "sh.601318", "sh.600900", "sh.688981",
    "sh.688111", "sh.603259", "sh.600276", "sh.601012", "sh.688012",
    "sz.000001", "sz.000858", "sz.002594", "sz.300750", "sz.300760",
    "sz.002415", "sz.000333", "sz.300059", "sz.002230", "sz.300124",
]


def fetch_one(bs, code):
    """拉单只最近收盘。返回 (code, price or None)。"""
    try:
        rs = bs.query_history_k_data_plus(
            code, "date,close",
            start_date="2026-06-20", end_date="2026-06-30", frequency="d")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return code, (rows[-1][1] if rows else None)
    except Exception:
        return code, None


def test_concurrency(workers, timeout=60):
    import baostock as bs
    bs.login()
    t = time.time()
    ok = 0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fetch_one, bs, c): c for c in TEST_CODES}
            for fut in concurrent.futures.as_completed(futs, timeout=timeout):
                _, price = fut.result()
                if price is not None:
                    ok += 1
    except concurrent.futures.TimeoutError:
        pass
    finally:
        bs.logout()
    dt = time.time() - t
    return ok, dt


if __name__ == "__main__":
    print("=" * 55)
    print("并发能力探测: 20 只个股, 试不同并发档")
    print("=" * 55)
    # baostock 单会话并发有限制, 但先看实测表现
    for w in (3, 8, 15):
        print(f"\n[并发 {w}] 拉 20 只(最多等 60s)...")
        try:
            ok, dt = test_concurrency(w, timeout=60)
            rate = ok / len(TEST_CODES) * 100
            print(f"  成功 {ok}/20 ({rate:.0f}%)  用时 {dt:.1f}s  "
                  f"→ 折算全市场1576只约 {dt/20*1576/60:.0f} 分钟")
        except Exception as e:
            print(f"  ✗ 报错: {type(e).__name__}: {str(e)[:80]}")
    print("\n" + "=" * 55)
    print("把每档的 成功率 和 用时 贴回去。")
    print("成功率高且用时短的那档, 就是你网络的并发甜蜜点。")
    print("=" * 55)
