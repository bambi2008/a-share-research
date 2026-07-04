#!/usr/bin/env python3
"""
扫描变化追踪 — 对比两次扫描结果，标记新增/退出/排名变动
"""
import json, os, sys, time


def _delta_path():
    d = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, 'frozen', False):
        d = os.path.dirname(sys.executable)
    return os.path.join(d, ".scan_delta.json")


def load_last_scan():
    """加载上次扫描的候选代码列表"""
    dp = _delta_path()
    if not os.path.exists(dp):
        return None
    try:
        data = json.load(open(dp, 'r', encoding='utf-8'))
        if time.time() - data.get("_ts", 0) < 86400 * 7:  # 7天内有效
            return data
    except Exception:
        pass
    return None


def save_scan(candidates, scan_time):
    """保存当前扫描结果"""
    dp = _delta_path()
    data = {
        "_ts": time.time(),
        "_time": scan_time,
        "codes": [c["code"] for c in candidates],
        "names": {c["code"]: c["name"] for c in candidates},
        "ranks": {c["code"]: i + 1 for i, c in enumerate(candidates)},
        "count": len(candidates),
    }
    try:
        json.dump(data, open(dp, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception:
        pass


def compute_delta(candidates):
    """对比上次扫描，计算变化。
    返回: {new_codes, exited_codes, big_movers, last_info, delta_summary}
    """
    last = load_last_scan()
    if not last:
        return None

    current_codes = {c["code"] for c in candidates}
    last_codes = set(last.get("codes", []))
    last_ranks = last.get("ranks", {})
    last_names = last.get("names", {})

    new_entries = current_codes - last_codes
    exits = last_codes - current_codes

    # 大变动（排名变化>=10）
    big_movers = []
    for i, c in enumerate(candidates):
        code = c["code"]
        old_rank = last_ranks.get(code)
        if old_rank:
            delta = old_rank - (i + 1)
            if abs(delta) >= 10:
                direction = "↑" if delta > 0 else "↓"
                big_movers.append({
                    "code": code,
                    "name": c.get("name", ""),
                    "old_rank": old_rank,
                    "new_rank": i + 1,
                    "delta": delta,
                    "direction": direction,
                })

    # 生成摘要
    parts = []
    if new_entries:
        names = [last_names.get(c, c) for c in list(new_entries)[:5]]
        parts.append(f"+{len(new_entries)}新进: {', '.join(names[:3])}")
    if exits:
        names = [c for c in list(exits)[:3]]
        parts.append(f"-{len(exits)}退出")
    if big_movers:
        movers = [f"{m['name']}{m['direction']}{abs(m['delta'])}" for m in big_movers[:3]]
        parts.append(f"排名变动: {', '.join(movers)}")

    return {
        "new_codes": new_entries,
        "exited_codes": exits,
        "big_movers": big_movers,
        "last_time": last.get("_time", ""),
        "last_count": last.get("count", 0),
        "delta_summary": " | ".join(parts) if parts else "排名基本不变",
    }
