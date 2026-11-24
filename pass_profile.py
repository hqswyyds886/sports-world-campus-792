# -*- coding: utf-8 -*-
"""从 PASS 样本提取 28 字段点结构的完整统计，作为改造与对拍的黄金基准。"""
import json, gzip, base64, statistics, sys, os

BASE = os.path.dirname(os.path.abspath(__file__))

def unbox(v):
    if not isinstance(v, str) or not v:
        return None
    try:
        return json.loads(gzip.decompress(base64.b64decode(v)))
    except Exception:
        return None

def load(name):
    return json.loads(open(os.path.join(BASE, name), encoding='utf-8').read())

samples = ['obs_PASS_1000000015.json', 'obs_PASS_1000000018.json']

for name in samples:
    d = load(name)
    rd = unbox(d.get('run_data') or '')
    loc = rd.get('allLocJson')
    pts = json.loads(loc) if isinstance(loc, str) else loc
    print("#" * 78)
    print(name, " 点数 =", len(pts))
    print("#" * 78)

    keys = list(pts[0].keys())
    print("字段数 =", len(keys))
    print("字段:", keys)
    print()

    n = len(pts)
    print("%-14s %-10s %-12s %-12s %-12s %s" % ("字段", "类型", "min", "max", "mean/唯一", "样本值"))
    print("-" * 96)
    for k in keys:
        vals = [p.get(k) for p in pts]
        types = set(type(v).__name__ for v in vals)
        tn = "/".join(sorted(types))
        try:
            nums = [float(v) for v in vals if v is not None and not isinstance(v, bool)]
            uniq = len(set(nums))
            if uniq == 1:
                print("%-14s %-10s %-12.6g %-12.6g %-12s %s" % (k, tn, min(nums), max(nums), "常量", repr(vals[0])[:40]))
            else:
                mean = statistics.fmean(nums) if nums else 0
                print("%-14s %-10s %-12.6g %-12.6g 唯一=%-6d %s" % (k, tn, min(nums), max(nums), uniq, repr(vals[0])[:40]))
        except Exception:
            uniq = sorted(set(str(v) for v in vals))[:4]
            print("%-14s %-10s %-12s %-12s 唯一=%-6d %s" % (k, tn, "-", "-", len(set(str(v) for v in vals)), uniq[:3]))
    print()

    # 逐点递增字段验证
    print("=== 关键序列前 8 点 ===")
    show = ['id','queueNum','count','radius','speed','avgSpeed','bdS','totalDis','totalTime','state','type','validDis','stepDistance']
    for i in range(min(8, n)):
        print("  [%d] " % i + "  ".join("%s=%s" % (k, pts[i].get(k)) for k in show if k in pts[i]))
    print()

    # type 分布
    from collections import Counter
    print("type 分布:", dict(Counter(p.get('type') for p in pts)))
    print("state 分布:", dict(Counter(p.get('state') for p in pts)))
    print("count 取值:", sorted(set(p.get('count') for p in pts)))
    print()

    # 采样间隔
    times = [p.get('flag') for p in pts]
    gaps = [b - a for a, b in zip(times, times[1:]) if isinstance(a,int) and isinstance(b,int)]
    if gaps:
        print("相邻点时间间隔 ms: min=%d max=%d mean=%.1f" % (min(gaps), max(gaps), statistics.fmean(gaps)))
    print()

    # segment_json
    seg = unbox(d.get('segment_json') or '')
    if isinstance(seg, list):
        print("segment_json 段数 =", len(seg))
        print("  段0:", json.dumps(seg[0], ensure_ascii=False)[:300])
    else:
        print("segment_json:", repr(seg)[:120])
    print()

    # laps
    laps = unbox(d.get('laps_json') or '')
    if isinstance(laps, list):
        print("laps_json 圈数 =", len(laps))
        for L in laps[:3]:
            print("  ", json.dumps(L, ensure_ascii=False)[:260])
    print()
    print()
