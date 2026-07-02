#!/usr/bin/env python3
"""data_source.py 纯逻辑单测 —— 不触网, 不依赖 akshare/baostock。"""
import os
import sys
import time
import tempfile
import importlib

# 让测试用临时缓存目录, 避免污染真实 data_cache
_TMP = tempfile.mkdtemp()
import data_source as ds
ds.CACHE_DIR = _TMP

PASS = 0
FAIL = 0

def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}")

print("── 代码前缀 / symbol ──")
check("沪主板 600519 -> sh", ds.market_prefix("600519") == "sh")
check("科创 688981 -> sh", ds.market_prefix("688981") == "sh")
check("深主板 000001 -> sz", ds.market_prefix("000001") == "sz")
check("创业 300750 -> sz", ds.market_prefix("300750") == "sz")
check("北交 830799 -> bj", ds.market_prefix("830799") == "bj")
check("新浪 symbol", ds.sina_symbol("600519") == "sh600519")
check("baostock symbol", ds.baostock_symbol("600519") == "sh.600519")
check("北交 baostock 归 sz 兜底", ds.baostock_symbol("830799") == "sz.830799")

print("── 超时包装 call_with_timeout ──")
check("正常透传返回值", ds.call_with_timeout(lambda x: x + 1, 5, 41) == 42)

_timed_out = False
try:
    ds.call_with_timeout(lambda: time.sleep(3), 0.3)
except TimeoutError:
    _timed_out = True
check("超时抛 TimeoutError", _timed_out)

_corrupt = False
def _boom():
    raise Exception("Error -3 while decompressing data: incorrect header check")
try:
    ds.call_with_timeout(_boom, 5)
except RuntimeError as e:
    _corrupt = "损坏" in str(e)
except Exception:
    pass
check("zlib 损坏 -> RuntimeError(可读提示)", _corrupt)

_reraised = False
try:
    ds.call_with_timeout(lambda: (_ for _ in ()).throw(ValueError("x")), 5)
except ValueError:
    _reraised = True
check("普通异常原样抛出", _reraised)

print("── 缓存 TTL ──")
ds._cache_set("t_key", {"600519": 1720.0})
data, age = ds._cache_get("t_key", ttl=3600)
check("写入后命中", data == {"600519": 1720.0})
check("age 为很小的正数", age is not None and 0 <= age < 5)
data2, age2 = ds._cache_get("t_key", ttl=0)  # ttl=0 立即过期
check("ttl=0 视为过期", data2 is None)
d3, a3 = ds._cache_get("missing_key", ttl=3600)
check("不存在返回 (None,None)", d3 is None and a3 is None)

print("── 覆盖率 / 新鲜度 / 预算 ──")
check("覆盖率带分母", ds._coverage({"a": 1, "b": 2}, {"a", "b", "c"}) == "覆盖 2/3")
check("覆盖率无分母", ds._coverage({"a": 1}, None) == "覆盖 1 只")
check("新鲜度 实时", ds._fmt_age(None) == "实时")
check("新鲜度 刚刚", ds._fmt_age(30) == "刚刚")
check("新鲜度 分钟", ds._fmt_age(600) == "10分钟前")
check("新鲜度 小时", ds._fmt_age(7200) == "2.0小时前")

exp = ds._deadline(0.2)
check("预算未到未过期", exp() is False)
time.sleep(0.25)
check("预算到期后为 True", exp() is True)

print("── 目标池哈希(供历史缓存键) ──")
h1 = ds._hash_codes(["600519", "000001", "300750"])
h2 = ds._hash_codes(["300750", "600519", "000001"])  # 乱序
check("哈希与顺序无关", h1 == h2)
check("哈希长度 10", len(h1) == 10)

print("── 无循环依赖 ──")
src = open(ds.__file__, encoding="utf-8").read()
check("data_source 不再 import scanner",
      "import scanner" not in src)
check("INDICES 内聚在 data_source", hasattr(ds, "INDICES") and len(ds.INDICES) == 3)

print(f"\n结果: {PASS} 通过, {FAIL} 失败")
sys.exit(1 if FAIL else 0)
