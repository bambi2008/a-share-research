#!/usr/bin/env python3
"""核心-卫星框架 综合单测 —— 纯逻辑, 不触网。"""
import sys

import portfolio_config as pc
import risk_engine as re
import momentum as mo
import satellite as sat
import report_panel as rp

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ {name}")

BK = pc.DEFAULT_BUCKETS

# ══════════════ 1. 三仓配置 ══════════════
print("── 三仓配置 ──")
check("目标权重和≈1", abs(sum(b["target"] for b in BK.values()) - 1.0) < 1e-9)
check("默认配置校验通过", pc.validate(BK) == [])
_bad = {"anchor": {"target": 0.5, "max": 0.4, "per_name_max": 0.1, "stop": None},
        "momentum": {"target": 0.3, "max": 0.4, "per_name_max": 0.07, "stop": -0.1},
        "satellite": {"target": 0.15, "max": 0.2, "per_name_max": 0.03, "stop": None}}
check("能查出 max<target", any("max" in p for p in pc.validate(_bad)))
check("卫星仓单票上限=3%", BK["satellite"]["per_name_max"] == 0.03)
check("动量仓止损=-10%", BK["momentum"]["stop"] == -0.10)

# ══════════════ 2. 配仓守门 ══════════════
print("── 配仓守门 ──")
EQ = 1_000_000
# 空仓下, 卫星买 2% ok, 买 4% 超单票上限(3%)
ok1, _ = re.check_buy([], EQ, "satellite", "300001", 0.02 * EQ, BK)
check("卫星 2% 放行", ok1 is True)
ok2, rs2 = re.check_buy([], EQ, "satellite", "300001", 0.04 * EQ, BK)
check("卫星 4% 拦截(超单票3%)", ok2 is False and any("单票" in r for r in rs2))
# 动量仓已有 38%, 再买 5% 会超仓位上限(40%)
poss = [{"code": "600001", "bucket": "momentum", "price": 10, "shares": 38000, "cost": 10}]
ok3, rs3 = re.check_buy(poss, EQ, "momentum", "600002", 0.05 * EQ, BK)
check("动量超仓位上限拦截", ok3 is False and any("上限" in r for r in rs3))
check("非法仓位拦截", re.check_buy([], EQ, "xxx", "600002", 100, BK)[0] is False)
# 可买余量
room = re.room_to_buy([], EQ, "satellite", "300001", BK)
check("卫星空仓可买余量=3%×EQ", abs(room - 0.03 * EQ) < 1)

# ══════════════ 3. 持仓体检 ══════════════
print("── 持仓体检 ──")
# 动量仓移动止损: 成本10, 最高15, 现价13.4 → 止损价=15×0.9=13.5, 现价<止损 → 触发
p_mom = {"code": "600003", "name": "X", "bucket": "momentum",
         "cost": 10.0, "high": 15.0, "price": 13.4, "shares": 100}
m = re.position_metrics(p_mom, BK)
check("移动止损价=最高×0.9", abs(m["stop_price"] - 13.5) < 1e-6)
check("盈亏基于成本(+34%)", abs(m["pnl_pct"] - 34.0) < 1e-6)
check("回撤基于最高(-10.67%)", abs(m["drawdown_pct"] - (13.4-15)/15*100) < 1e-6)
check("触发止损告警", any(a.startswith("⛔") for a in m["alerts"]))
# 逼近但未破: 现价13.6 → 距止损(13.6-13.5)/13.6≈0.74% <3% → 逼近告警
p_near = dict(p_mom); p_near["price"] = 13.6
mn = re.position_metrics(p_near, BK)
check("逼近止损告警", any(a.startswith("⚠️") for a in mn["alerts"]))
# 卫星仓无机械止损但有投机标记
p_sat = {"code": "300009", "name": "Y", "bucket": "satellite",
         "cost": 20, "price": 25, "shares": 100}
ms = re.position_metrics(p_sat, BK)
check("卫星无止损价", ms["stop_price"] is None)
check("卫星投机标记", any("卫星" in a for a in ms["alerts"]))

# ══════════════ 4. 组合视图 ══════════════
print("── 组合视图 ──")
book = [
    {"code": "600001", "bucket": "anchor", "price": 10, "shares": 40000, "cost": 9, "industry": "银行"},
    {"code": "600002", "bucket": "momentum", "price": 20, "shares": 10000, "cost": 18, "high": 22, "industry": "半导体"},
    {"code": "300003", "bucket": "satellite", "price": 30, "shares": 1000, "cost": 30, "industry": "半导体"},
]
exp = re.bucket_exposure(book, EQ, BK)
check("压舱仓 mv=40万", abs(exp["anchor"]["mv"] - 400000) < 1)
check("现金=剩余", abs(exp["_cash"]["mv"] - (EQ - 400000 - 200000 - 30000)) < 1)
check("动量仓未超上限", exp["momentum"]["over"] is False)
nw, nc, iw, ic = re.concentration(book, EQ)
check("最大单票=压舱40%", abs(nw - 0.40) < 1e-9 and nc == "600001")
check("最大行业=银行40%", ic == "银行" and abs(iw - 0.40) < 1e-9)
ml = re.max_loss_assumption(book, EQ, BK)
check("卫星全灭=3%", abs(ml["satellite_wipeout_pct"] - 3.0) < 1e-6)
check("动量全止损=20%×10%=2%", abs(ml["momentum_allstop_pct"] - 2.0) < 1e-6)
check("合计=5%", abs(ml["combined_pct"] - 5.0) < 1e-6)

# ══════════════ 5. 动量指标 ══════════════
print("── 动量指标 ──")
up = [10 + i * 0.1 for i in range(80)]      # 单调上行
down = [20 - i * 0.1 for i in range(80)]    # 单调下行
check("上行 20日收益>0", mo.ret(up, 20) > 0)
check("下行 20日收益<0", mo.ret(down, 20) < 0)
check("长度不足返回 None", mo.ret([1, 2, 3], 20) is None)
check("SMA 正确", abs(mo.sma([1, 2, 3, 4], 2) - 3.5) < 1e-9)
check("上行站上均线", mo.above_sma(up, 20) is True)
check("下行跌破均线", mo.above_sma(down, 20) is False)
check("相对强弱: 个股强于指数为正",
      mo.relative_strength(up, [10 + i * 0.05 for i in range(80)], 20) > 0)
s_up, _ = mo.momentum_score(up)
s_dn, _ = mo.momentum_score(down)
check("上行动量分 > 下行动量分", s_up > s_dn)
ranked = mo.rank_momentum({"UP": {"close": up}, "DN": {"close": down}})
check("排名: 上行在前", ranked[0]["code"] == "UP")
check("短序列被剔除", mo.rank_momentum({"SHORT": {"close": [1, 2, 3]}}) == [])

# ══════════════ 6. 卫星凸性筛选 ══════════════
print("── 卫星凸性筛选 ──")
cands = [
    {"code": "300100", "name": "A", "industry": "半导体", "rev_growth": 80, "mktcap": 120},
    {"code": "300101", "name": "B", "industry": "光伏设备", "rev_growth": 50, "mktcap": 90},
    {"code": "300102", "name": "C", "industry": "半导体", "rev_growth": 45, "mktcap": 150},
    {"code": "600200", "name": "D", "industry": "银行", "rev_growth": 90, "mktcap": 100},   # 非主题
    {"code": "300103", "name": "E", "industry": "电池", "rev_growth": 20, "mktcap": 80},    # 增速不足
    {"code": "300104", "name": "F", "industry": "半导体", "rev_growth": 60, "mktcap": 900}, # 市值过大
]
picks, notes = sat.screen_satellite(cands, max_names=5)
codes = [p["code"] for p in picks]
check("非主题(银行)被剔除", "600200" not in codes)
check("增速不足被剔除", "300103" not in codes)
check("大市值被剔除", "300104" not in codes)
check("按增速降序(A 第一)", picks[0]["code"] == "300100")
check("全部打投机标记", all(p["speculative"] for p in picks))
check("全部归入卫星仓", all(p["bucket"] == "satellite" for p in picks))
empty, en = sat.screen_satellite([], max_names=5)
check("空候选→空仓提示", empty == [] and any("空仓" in n for n in en))

# ══════════════ 7. 风控面板渲染 ══════════════
print("── 风控面板渲染 ──")
panel = rp.build_risk_panel(book, EQ, BK)
check("面板含三仓敞口", "三仓敞口" in panel)
check("面板含最坏情形", "卫星全灭" in panel)
check("面板含持仓体检", "持仓体检" in panel)
check("面板是非空字符串", isinstance(panel, str) and len(panel) > 100)
panel_empty = rp.build_risk_panel([], EQ, BK)
check("空持仓面板不报错", "无持仓" in panel_empty)

print(f"\n结果: {PASS} 通过, {FAIL} 失败")
sys.exit(1 if FAIL else 0)
