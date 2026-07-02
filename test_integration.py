#!/usr/bin/env python3
"""position.py + enrich_report.py 集成测试 —— 离线, 注入假依赖。"""
import json
import os
import sys
import tempfile

# 用临时目录当 app 目录, 隔离真实 portfolio.json
_TMP = tempfile.mkdtemp()

import position as pos
import enrich_report as er
pos._app_dir = lambda: _TMP   # 重定向账户文件到临时目录

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ {name}")

# ══════════ position.py ══════════
print("── 账户读写 / 默认 ──")
p = pos.load_portfolio()
check("空账户默认 cash=0", p["cash"] == 0.0)
check("默认 holdings 空", p["holdings"] == {})

# 写一个真实的三仓账户
pos.save_portfolio({"cash": 100000, "trades": [], "holdings": {}})
pos.add_position("600519", "贵州茅台", cost=1500, date="2026-03-01",
                 bucket="anchor", shares=300, high=1650, industry="白酒")
pos.add_position("688981", "中芯国际", cost=85, date="2026-05-10",
                 bucket="momentum", shares=2000, high=110, industry="半导体")
pos.add_position("300394", "天孚通信", cost=120, date="2026-06-01",
                 bucket="satellite", shares=250, high=156, industry="通信设备")

print("── 字段补全 / 迁移 ──")
p = pos.load_portfolio()
check("三只持仓写入", len(p["holdings"]) == 3)
check("bucket 正确", p["holdings"]["688981"]["bucket"] == "momentum")
check("shares 正确", p["holdings"]["600519"]["shares"] == 300)

print("── 估值 ──")
price_map = {"600519": 1620, "688981": 98, "300394": 156}
eq = pos.total_equity(price_map)
# 现金10万 + 茅台300×1620 + 中芯2000×98 + 天孚250×156
expect = 100000 + 300*1620 + 2000*98 + 250*156
check("总资产 = 现金+持仓市值", abs(eq - expect) < 1e-6)

print("── 移动止损基准维护 ──")
# 中芯现价98<high110 不动; 假设茅台涨到1700>1650 应抬高
n = pos.update_highs({"600519": 1700, "688981": 98, "300394": 156})
check("创新高抬高 high", n == 1 and pos.load_portfolio()["holdings"]["600519"]["high"] == 1700)

print("── 体检(委托 risk_engine) ──")
positions, alerts = pos.check_positions(price_map)
check("返回3只", len(positions) == 3)
check("含旧字段 pnl_pct", all("pnl_pct" in r for r in positions))
check("含新字段 bucket", all("bucket" in r for r in positions))
mid = next(r for r in positions if r["code"] == "688981")
# 中芯 high=110(未被上一步改), 现价98, 移动止损价=110×0.9=99 → 98<99 触发
check("中芯触发移动止损", any(a.startswith("⛔") for a in mid["alerts"]))
check("止损汇总非空", len(alerts) >= 1)
# 兼容旧接口
check("load_holdings 兼容", len(pos.load_holdings()) == 3)

# ══════════ enrich_report.py (注入假数据源) ══════════
print("── 报告扩展 (注入假依赖) ──")
candidates = [
    {"code": "300100", "name": "A", "industry": "半导体", "rev_growth": 80, "mktcap": 120, "profit_growth": 60},
    {"code": "300101", "name": "B", "industry": "光伏设备", "rev_growth": 50, "mktcap": 90, "profit_growth": 30},
    {"code": "600200", "name": "C", "industry": "银行", "rev_growth": 90, "mktcap": 100, "profit_growth": 40},
]

class FakeDS:
    """假数据源: 给 300100 造上行序列, 300101 造下行序列。"""
    def get_price_history(self, codes, days=120):
        up = [10 + i * 0.1 for i in range(80)]
        dn = [20 - i * 0.1 for i in range(80)]
        hist = {}
        for c in codes:
            hist[c] = {"close": up if c == "300100" else dn}
        return hist, "fake(测试)"

# 卫星段: 银行应被剔除
sat_sec = er.build_satellite_section(candidates)
check("卫星段含标题", "高凸卫星仓候选" in sat_sec)
check("卫星段剔除银行", "600200" not in sat_sec)
check("卫星段含半导体A", "300100" in sat_sec)

# 动量段: 上行的 300100 应排在下行的 300101 前
mom_sec = er.build_momentum_section(candidates, price_map, data_source_mod=FakeDS())
check("动量段含标题", "动量排名" in mom_sec)
i100 = mom_sec.find("300100")
i101 = mom_sec.find("300101")
check("上行标的排在前", i100 != -1 and i101 != -1 and i100 < i101)

# 风控段: 用当前临时账户
risk_sec = er.build_risk_section(price_map)
check("风控段含三仓敞口", "三仓敞口" in risk_sec)
check("风控段含最坏情形", "卫星全灭" in risk_sec)

# 完整扩展: 注入假 ds, 三块齐全, 不抛异常
ext = er.build_extension(candidates, price_map, data_source_mod=FakeDS())
check("扩展含三块", ("高凸卫星仓" in ext) and ("动量排名" in ext) and ("三仓敞口" in ext))
check("扩展为非空字符串", isinstance(ext, str) and len(ext) > 200)

# 容错: 数据源抛异常时, 动量段降级但不炸整体
class BrokenDS:
    def get_price_history(self, codes, days=120):
        raise RuntimeError("模拟取数失败")
ext2 = er.build_extension(candidates, price_map, data_source_mod=BrokenDS())
check("单块失败不影响其余", ("高凸卫星仓" in ext2) and ("三仓敞口" in ext2))
check("失败块给出降级提示", "生成失败" in ext2 or "无法计算" in ext2 or "不足" in ext2)

print(f"\n结果: {PASS} 通过, {FAIL} 失败")
sys.exit(1 if FAIL else 0)
