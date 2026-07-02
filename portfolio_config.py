#!/usr/bin/env python3
"""
三仓(核心-卫星杠铃)配置
========================
- anchor   压舱仓  : 质量价值 + 现金, 低换手, 稳住盘面
- momentum 动量弹性仓: 短中期趋势/主题轮动, 移动止损
- satellite 高凸卫星仓: 少数高成长/爆发标的, 接受"归零 or 翻几倍", 硬性限仓

字段:
  target        目标权重(占总资产, 含现金)
  max           权重硬上限(配仓守门用: 买入不得使该仓超过此值)
  per_name_max  单票权重硬上限
  stop          止损线(相对参考价的跌幅, 负数); None 表示不设机械止损
  trailing      True=移动止损(参考"买入后最高价"), False/缺省=固定止损(参考成本价)
  speculative   True=投机标记(卫星仓), 报告中显著提示、且不得混入核心池

设计口径(与前面对齐):
  卫星仓 15% + 单票 3%  → 卫星全灭最多亏 15%, 伤不到根本;
  动量仓 35% + 移动止损 -10% → 亏的时候亏小的, 赚的时候让它跑;
  压舱仓 50% → A/B 翻车时的稳定器。
"""
from __future__ import annotations
import json
import os
import sys

DEFAULT_BUCKETS = {
    "anchor": {
        "name": "压舱仓", "target": 0.50, "max": 0.60,
        "per_name_max": 0.10, "stop": None, "trailing": False,
        "speculative": False,
        "desc": "质量价值 + 现金, 低换手",
    },
    "momentum": {
        "name": "动量弹性仓", "target": 0.35, "max": 0.40,
        "per_name_max": 0.07, "stop": -0.10, "trailing": True,
        "speculative": False,
        "desc": "短中期趋势/主题轮动, 移动止损 -10%",
    },
    "satellite": {
        "name": "高凸卫星仓", "target": 0.15, "max": 0.20,
        "per_name_max": 0.03, "stop": None, "trailing": False,
        "speculative": True,
        "desc": "少数高成长/爆发标的, 接受归零or翻几倍, 单票≤3%",
    },
}

BUCKET_ORDER = ["anchor", "momentum", "satellite"]


def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_path() -> str:
    return os.path.join(_app_dir(), "three_bucket_config.json")


def validate(buckets: dict) -> list:
    """返回问题列表(空=通过)。校验目标和≈1、上限≥目标、单票上限合理。"""
    problems = []
    total = sum(b["target"] for b in buckets.values())
    if abs(total - 1.0) > 0.02:
        problems.append(f"三仓目标权重之和={total:.2f}, 应≈1.00")
    for key, b in buckets.items():
        if b["max"] < b["target"]:
            problems.append(f"{key}: max({b['max']}) < target({b['target']})")
        if b["per_name_max"] > b["max"]:
            problems.append(f"{key}: 单票上限({b['per_name_max']}) > 仓位上限({b['max']})")
        if b["stop"] is not None and not (-1.0 < b["stop"] < 0):
            problems.append(f"{key}: stop({b['stop']}) 应为 (-1,0) 的负数")
    return problems


def load() -> dict:
    """读取三仓配置; 不存在则写入默认模板并返回。"""
    path = config_path()
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_BUCKETS, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return {k: v.copy() for k, v in DEFAULT_BUCKETS.items()}
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # 补全缺失字段
        for k, v in DEFAULT_BUCKETS.items():
            if k not in cfg:
                cfg[k] = v.copy()
            else:
                for fk, fv in v.items():
                    cfg[k].setdefault(fk, fv)
        return cfg
    except Exception:
        return {k: v.copy() for k, v in DEFAULT_BUCKETS.items()}
