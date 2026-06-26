#!/usr/bin/env python3
"""港股数据多源容灾"""
import akshare as ak

def fetch_hk_spot(timeout=60):
    """获取港股行情。主源:新浪 stock_hk_spot → 备用:直接API"""
    # 主源: 试试不用东财的
    for fn_name in ['stock_hk_spot']:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        try:
            df = fn()
            if df is not None and len(df) > 0:
                return df, fn_name
        except Exception:
            continue
    
    # 备用: 东财(大概率挂)
    try:
        df = ak.stock_hk_spot_em()
        return df, "em"
    except Exception:
        pass
    
    return None, "全部失败"
