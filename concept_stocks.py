#!/usr/bin/env python3
"""
热门概念板块 — 获取概念成分股
数据源: 搜狐证券概念板块页面 → 解析成分股代码
缓存: .concept_cache.json (24小时有效)
"""
import json, os, sys, urllib.request, re, time

# ── 热门概念列表 ──
def _load_concepts():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "concepts.json")
    if getattr(sys, 'frozen', False):
        p = os.path.join(os.path.dirname(sys.executable), "concepts.json")
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f).get("concepts", [])
    except Exception:
        return [
            {"name": "先进封装", "code": "bk_7956"},
            {"name": "商业航天", "code": "bk_7338"},
            {"name": "氟化工概念", "code": "bk_4418"},
            {"name": "算力租赁", "code": "bk_6620"},
            {"name": "玻璃基板", "code": "bk_7318"},
            {"name": "人形机器人", "code": "bk_7484"},
        ]

HOT_CONCEPTS = _load_concepts()


def _cache_path():
    d = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, 'frozen', False):
        d = os.path.dirname(sys.executable)
    return os.path.join(d, ".concept_cache.json")


def _is_cache_valid():
    """缓存是否在24小时内"""
    cp = _cache_path()
    if not os.path.exists(cp):
        return False
    try:
        cache = json.load(open(cp, 'r', encoding='utf-8'))
        return (time.time() - cache.get("_ts", 0)) < 86400
    except Exception:
        return False


def fetch_concept_stocks(progress_callback=None, force_refresh=False):
    """获取所有热门概念的成分股代码集合。先试缓存，过期则从搜狐抓取。
    返回: {concept_name: set(codes), ...}
    """
    cp = _cache_path()

    # 缓存命中
    if not force_refresh and _is_cache_valid():
        try:
            cache = json.load(open(cp, 'r', encoding='utf-8'))
            result = {}
            for c in HOT_CONCEPTS:
                name = c["name"]
                codes = cache.get(name, [])
                if codes:
                    result[name] = set(codes)
            if result:
                if progress_callback:
                    progress_callback(f"缓存命中 ({len(result)}个概念)")
                return result
        except Exception:
            pass

    # 从搜狐抓取
    result = {}
    total = len(HOT_CONCEPTS)
    for i, c in enumerate(HOT_CONCEPTS):
        name = c["name"]
        code = c["code"]
        if progress_callback:
            progress_callback(f"概念 {i+1}/{total}: {name}")

        try:
            url = f"https://q.stock.sohu.com/cn/{code}.shtml"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("gbk", errors="replace")

            codes_found = set(re.findall(r'>(\d{6})<', html))
            valid = {c for c in codes_found if c[0] in '03689'}
            result[name] = valid
        except Exception as e:
            if progress_callback:
                progress_callback(f"  {name} 获取失败: {e}")
            result[name] = set()

    # 写缓存
    try:
        cache = {"_ts": time.time()}
        for k, v in result.items():
            cache[k] = list(v)
        json.dump(cache, open(cp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    except Exception:
        pass

    return result


def get_concept_codes(concept_stocks=None, progress_callback=None):
    """返回所有概念成分股的合并集合 + {code: [concept_names]} 映射。"""
    if concept_stocks is None:
        concept_stocks = fetch_concept_stocks(progress_callback=progress_callback)

    all_codes = set()
    code_concepts = {}
    for name, codes in concept_stocks.items():
        all_codes.update(codes)
        for c in codes:
            code_concepts.setdefault(c, []).append(name)
    return all_codes, code_concepts
