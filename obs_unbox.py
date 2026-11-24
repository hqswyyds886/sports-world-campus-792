# -*- coding: utf-8 -*-
"""解开 OBS 明细里的 gzip+base64 字段，逐点对比 PASS / CHEAT 记录。"""
import json, gzip, base64, glob, os, sys, io

def unbox(v):
    if not isinstance(v, str) or not v:
        return None
    try:
        raw = gzip.decompress(base64.b64decode(v))
    except Exception:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw.decode("utf-8", "replace")

def load(f):
    return json.loads(open(f, encoding="utf-8").read())

files = sys.argv[1:] or sorted(glob.glob("obs_*.json"))
for f in files:
    print("#" * 80)
    print(f)
    print("#" * 80)
    d = load(f)
    for k, v in d.items():
        u = unbox(v)
        if u is None:
            print("  %-20s <不可解>" % k)
            continue
        if isinstance(u, list):
            print("  %-20s list[%d]" % (k, len(u)))
            if u and isinstance(u[0], dict):
                print("     点0 keys: %s" % list(u[0].keys()))
                print("     点0: %s" % json.dumps(u[0], ensure_ascii=False)[:400])
                if len(u) > 1:
                    print("     点1: %s" % json.dumps(u[1], ensure_ascii=False)[:400])
        elif isinstance(u, dict):
            print("  %-20s dict: %s" % (k, json.dumps(u, ensure_ascii=False)[:400]))
        else:
            print("  %-20s %s" % (k, str(u)[:200]))
    print()
