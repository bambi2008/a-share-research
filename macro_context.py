#!/usr/bin/env python3
"""
宏观背景面板 — PMI, CPI, M2 等关键宏观指标
数据源: akshare macro_china_* 系列
"""
import json, os, sys, time


def _cache_path():
    d = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, 'frozen', False):
        d = os.path.dirname(sys.executable)
    return os.path.join(d, ".macro_cache.json")


def fetch_macro_context(progress_callback=None, force_refresh=False):
    """获取最新宏观背景数据。24h缓存。
    返回: {pmi, cpi, m2, summary}
    """
    cp = _cache_path()

    # 缓存
    if not force_refresh and os.path.exists(cp):
        try:
            cache = json.load(open(cp, 'r', encoding='utf-8'))
            if time.time() - cache.get("_ts", 0) < 86400:
                return cache
        except Exception:
            pass

    def log(msg):
        if progress_callback:
            progress_callback(msg)

    import akshare as ak

    result = {}

    # PMI
    try:
        df = ak.macro_china_pmi_yearly()
        if len(df) > 0:
            last = df.iloc[-1]
            result["pmi"] = float(last.iloc[1]) if len(last) > 1 else None
            result["pmi_date"] = str(last.iloc[0])
            log(f"  PMI: {result['pmi']}")
    except Exception as e:
        log(f"  PMI跳过: {e}")
        result["pmi"] = None

    # CPI
    try:
        df = ak.macro_china_cpi_yearly()
        if len(df) > 0:
            last = df.iloc[-1]
            result["cpi"] = float(last.iloc[1]) if len(last) > 1 else None
            result["cpi_date"] = str(last.iloc[0])
            log(f"  CPI: {result['cpi']}%")
    except Exception as e:
        log(f"  CPI跳过: {e}")
        result["cpi"] = None

    # M2
    try:
        df = ak.macro_china_money_supply()
        if len(df) > 0:
            last = df.iloc[-1]
            # M2通常在第3-4列
            for col_idx in [2, 3, 4]:
                try:
                    val = float(last.iloc[col_idx])
                    if 100 < val < 500:  # M2通常在200-300万亿
                        result["m2"] = val
                        break
                except (ValueError, TypeError, IndexError):
                    continue
            result["m2_date"] = str(last.iloc[0])
            log(f"  M2: {result.get('m2', 'N/A')}万亿")
    except Exception as e:
        log(f"  M2跳过: {e}")
        result["m2"] = None

    # 生成摘要
    parts = []
    if result.get("pmi"):
        status = "扩张" if result["pmi"] >= 50 else "收缩"
        parts.append(f"PMI {result['pmi']:.1f}({status})")
    if result.get("cpi") is not None:
        parts.append(f"CPI {result['cpi']:.1f}%")
    if result.get("m2"):
        parts.append(f"M2 {result['m2']:.0f}万亿")

    result["summary"] = " | ".join(parts) if parts else "宏观数据暂缺"
    result["_ts"] = time.time()

    # 缓存
    try:
        json.dump(result, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception:
        pass

    return result


def macro_prompt_context(macro_data):
    """生成注入 LLM prompt 的宏观背景文本"""
    if not macro_data:
        return ""
    s = macro_data.get("summary", "")
    if not s:
        return ""
    lines = [
        "",
        "## 当前宏观背景",
        f"{s}",
        "请在分析时考虑以上宏观环境对行业和个股的影响。",
    ]
    return "\n".join(lines)
