import json, os, sys, tempfile
_TMP = tempfile.mkdtemp()
import portfolio as pf
pf._app_dir = lambda: _TMP
import investment_advice as ia

P = F = 0
def ck(n, c):
    global P, F
    if c: P += 1; print(f"  OK {n}")
    else: F += 1; print(f"  XX {n}")

print("== portfolio v2 兼容+三仓 ==")
# 模拟旧持仓（无 bucket/high）写盘，再 load 应自动补全
pf.save({"cash":100000,"trades":[],"holdings":{
    "600519":{"shares":300,"cost_basis":450000,"avg_cost":1500,"name":"贵州茅台"}}})
d = pf.load()
ck("旧持仓自动补 bucket=anchor", d["holdings"]["600519"]["bucket"]=="anchor")
ck("旧持仓自动补 high=成本", d["holdings"]["600519"]["high"]==1500)

# 买入带 bucket
pf.buy("688981","中芯国际",85,2000,date="2026-05-10",bucket="momentum")
d = pf.load()
ck("买入归入动量仓", d["holdings"]["688981"]["bucket"]=="momentum")
ck("现金扣减正确", abs(d["cash"]-(100000-85*2000))<1e-6)

pm = {"600519":1620,"688981":98}
# 移动止损基准维护：中芯涨到110应抬high
n = pf.update_highs({"688981":110})
ck("创新高抬 high", n==1 and pf.load()["holdings"]["688981"]["high"]==110)

# 总资产 = 现金 + 持仓市值
eq = pf.total_equity(pm)
d = pf.load()
expect = d["cash"] + 300*1620 + 2000*98
ck("total_equity 正确", abs(eq-expect)<1e-6)

# 修正后的 total_pnl：茅台(1620-1500)*300 + 中芯(98-85)*2000
st = pf.get_portfolio_status(pm)
exp_pnl = (1620-1500)*300 + (98-85)*2000
ck("total_pnl 修正正确", abs(st["total_pnl"]-exp_pnl)<1e-6)
ck("to_risk_positions 带 bucket/high", all("bucket" in p and "high" in p for p in pf.to_risk_positions(pm)))

print("== investment_advice 硬规则 ==")
cands = [
    {"code":"300100","name":"A","industry":"半导体","rev_growth":80,"mktcap":120,"pe":40,"roe":15,"price":50},
    {"code":"600036","name":"招行","industry":"银行","rev_growth":5,"mktcap":9000,"pe":6,"roe":16,"price":40},
]
# 成长模式：高增速中小盘→动量仓，止损-10%
plans = ia.compute_rule_based_plan(cands, growth_mode=True, equity=100000)
pa = next(p for p in plans if p["code"]=="300100")
ck("高增速中小盘归动量仓", pa["bucket"]=="momentum")
ck("动量仓止损价=现价×0.9", abs(pa["stop_price"]-50*0.9)<1e-6)
ck("动量单票上限7%→可买7000", abs(pa["max_buy_amount"]-7000)<1e-6)
pb = next(p for p in plans if p["code"]=="600036")
ck("大盘低增速归压舱仓", pb["bucket"]=="anchor")
ck("压舱仓无机械止损", pb["stop_price"] is None)

# 爆发模式：全归卫星仓，单票3%
plans2 = ia.compute_rule_based_plan(cands, boom_mode=True, equity=100000)
ck("爆发模式归卫星仓", all(p["bucket"]=="satellite" for p in plans2))
ck("卫星单票3%→可买3000", abs(plans2[0]["max_buy_amount"]-3000)<1e-6)

# 完整生成（注入假LLM，不联网）
def fake_llm(messages, temperature=0.4, max_tokens=2000):
    # 校验：prompt 明确禁止报价格
    txt = messages[0]["content"]
    assert "不要给出任何买入价" in txt or "不要输出任何价格" in txt
    return "【一、板块判断】积极。\n【二、候选点评】· 300100 A → 推荐 → 高增速..."
scan = {"candidates_full":cands,"industry_count":2,"total_stocks":100}
rep = ia.generate_advice(scan, growth_mode=True, llm_chat_fn=fake_llm, equity=100000)
ck("报告含风控计划表", "系统风控计划" in rep)
ck("报告含定性分析", "板块判断" in rep)
ck("报告含免责声明", "不构成投资建议" in rep)
ck("报告不含瞎报预测字样", "12-18月" not in rep and "触及" not in rep)

print(f"\n结果: {P} 通过, {F} 失败")
sys.exit(1 if F else 0)
