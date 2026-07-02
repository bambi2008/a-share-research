#!/usr/bin/env python3
"""探测备用数据源"""
import akshare as ak

print("=== 备用行情源 ===")
# 腾讯
for fn in ['stock_zh_a_spot_tx', 'stock_zh_a_hist_tx']:
    try:
        f = getattr(ak, fn, None)
        if f:
            df = f() if 'spot' in fn else f(symbol='sh600519', period='daily', start_date='20260601', end_date='20260620')
            print(f"✅ {fn}: {len(df)} rows, cols={list(df.columns)[:6]}")
        else:
            print(f"❌ {fn}: 函数不存在")
    except Exception as e:
        print(f"⚠️ {fn}: {type(e).__name__}: {str(e)[:60]}")

# 同花顺行业
print("\n=== 同花顺行情 ===")
for fn in ['stock_board_industry_spot_ths', 'stock_board_concept_spot_ths']:
    try:
        f = getattr(ak, fn, None)
        if f:
            print(f"✅ {fn}: 函数存在")
        else:
            print(f"❌ {fn}: 不存在")
    except Exception as e:
        print(f"⚠️ {fn}: {e}")

# baostock
print("\n=== baostock ===")
try:
    import baostock as bs
    bs.login()
    rs = bs.query_history_k_data_plus("sh.600519", "date,close", start_date='2026-06-01', end_date='2026-06-20')
    rows = []
    while rs.next(): rows.append(rs.get_row_data())
    bs.logout()
    print(f"✅ baostock: {len(rows)} rows")
except ImportError:
    print("❌ baostock 未安装")
except Exception as e:
    print(f"⚠️ baostock: {e}")
