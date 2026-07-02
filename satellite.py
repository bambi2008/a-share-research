#!/usr/bin/env python3
"""
卫星凸性扫描 (B 高凸卫星仓)
===========================
把原 BOOM_MODE 改造成正规的"高凸性"筛选, 并强制打投机标记 + 硬限仓。

凸性 = 下行有下限(单票≤3%, 卫星仓≤15%), 上行不封顶(押中翻几倍)。
所以刻意"少而精": 只取少数几只、按营收加速度排序、限制单一行业占比。

筛选逻辑为纯函数(输入候选行 dict 列表), 可单测。
"""
from __future__ import annotations

# 主题行业(产业趋势暴露, 非收益承诺)
DEFAULT_THEME_SECTORS = [
    "半导体", "软件开发", "IT服务Ⅱ", "通信设备", "计算机设备",
    "自动化设备", "光学光电子", "消费电子",
    "航空装备Ⅱ", "航天装备Ⅱ",
    "电池", "光伏设备", "电网设备",
    "化学制药", "生物制品", "医疗器械", "医疗服务",
    "金属新材料", "非金属材料Ⅱ",
]


def screen_satellite(candidates,
                     rev_min: float = 30.0,
                     mktcap_min: float = 30.0,
                     mktcap_max: float = 300.0,
                     theme_sectors=None,
                     max_names: int = 5,
                     max_industry_share: float = 0.6):
    """卫星凸性筛选。

    参数:
      rev_min       营收同比增速下限(%), 抓爆发拐点
      mktcap_min/max 流通市值区间(亿), 锁定中小盘(大盘难翻倍)
      theme_sectors 主题行业白名单
      max_names     最多取几只(强制"少而精", 凸性的关键)
      max_industry_share 单一行业在卫星池的占比上限(分散主题风险)

    输入 candidates: [{code,name,rev_growth,mktcap,industry,profit_growth,...}, ...]
    返回 (picks, notes):
      picks 每只附加 bucket='satellite', speculative=True, per_name_cap 提示
      notes 为筛选过程说明列表
    """
    theme = set(theme_sectors or DEFAULT_THEME_SECTORS)
    notes = []

    pool = []
    for c in candidates:
        ind = c.get("industry")
        rev = c.get("rev_growth")
        mv = c.get("mktcap")
        is_concept = bool(c.get("concepts"))  # 概念股不受行业限制
        if not is_concept and ind not in theme:
            continue
        if rev is None or rev < rev_min:
            continue
        # 市值有则卡区间; 无市值数据则保留但标注(宁可多看一眼)
        if mv is not None and not (mktcap_min <= mv <= mktcap_max):
            continue
        pool.append(c)

    # 按营收加速度(增速)降序 —— 凸性来自加速拐点
    pool.sort(key=lambda x: x.get("rev_growth") or 0.0, reverse=True)

    # 单一行业占比控制: 逐只纳入, 超过上限的行业不再追加
    picks, ind_count = [], {}
    for c in pool:
        if len(picks) >= max_names:
            break
        ind = c.get("industry")
        # 若纳入后该行业占比会超限, 跳过(除非池子太小)
        prospective = (ind_count.get(ind, 0) + 1) / (len(picks) + 1)
        if prospective > max_industry_share and len(picks) >= 2:
            continue
        item = dict(c)
        item["bucket"] = "satellite"
        item["speculative"] = True
        item["per_name_cap_note"] = "单票≤总资产3%"
        picks.append(item)
        ind_count[ind] = ind_count.get(ind, 0) + 1

    notes.append(f"主题白名单 {len(theme)} 行业; 营收增速≥{rev_min:.0f}%; "
                 f"市值 {mktcap_min:.0f}-{mktcap_max:.0f}亿; 最多 {max_names} 只")
    if not picks:
        notes.append("⚠️ 无标的入选(条件偏严或数据缺失), 本周卫星仓建议空仓")
    else:
        notes.append(f"入选 {len(picks)} 只, 行业分布: " +
                     ", ".join(f"{k}×{v}" for k, v in ind_count.items()))
    notes.append("🎲 全部为投机标的: 用输得起的钱, 卫星仓合计≤15%")
    return picks, notes
