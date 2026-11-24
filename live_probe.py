# -*- coding: utf-8 -*-
"""实时拉取规则 + 围栏 + 点位，打印完整明细，用于提交前核对。不提交任何东西。"""
import os, sys, json

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")

from sport_client import SportClient792
from core.session import load_session
from config_loader import get_session_file_path

sess = load_session(get_session_file_path())
cli = SportClient792(uid=sess.get("uid"), token=sess.get("token"), unid=sess.get("unid"))

print("=" * 80)
print("1. 跑步规则 runModePolicy (runMode=1 计分跑)")
print("=" * 80)
rule = cli.get_run_policy(run_mode=1)
if rule is None:
    print("  拉取失败:", cli.policy.last_policy_error)
    sys.exit(1)
for name in ("policy", "min_distance", "valid_time", "min_run_time",
             "freeze_run_time", "pace_range", "step_range", "timestamp"):
    print("  %-18s %s" % (name, getattr(rule, name, "<无字段>")))
raw = getattr(rule, "raw", None) or {}
extra = {k: v for k, v in raw.items()
         if k not in ("policy", "minDistance", "validTime", "minRunTime",
                      "freezeRunTime", "speedTop", "speedBottom",
                      "stepTop", "stepBottom")}
if extra:
    print("  其他原始字段:")
    for k in sorted(extra):
        v = extra[k]
        s = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else repr(v)
        print("    %-24s %s" % (k, s[:150]))

print()
print("=" * 80)
print("2. 电子围栏")
print("=" * 80)
fences = cli.get_geo_fences()
print("  围栏数量: %d" % len(fences))
for f in fences:
    ring = getattr(f, "ring", None) or []
    print("  id=%s  name=%r  环点数=%d" % (
        getattr(f, "id", None), getattr(f, "name", None), len(ring)))
    for pt in ring:
        print("      %s" % (pt,))
    pp = getattr(f, "pass_points", None) or []
    print("  围栏内必经点: %d 个" % len(pp))
    for x in pp:
        print("      %s" % json.dumps(x, ensure_ascii=False, default=str)[:200])

print()
print("=" * 80)
print("3. 官方打卡点位（计分跑）")
print("=" * 80)
if not fences:
    print("  无围栏，跳过")
    sys.exit(0)
points = cli.policy.get_checkpoints_for_run(fences[0], rule=rule)
print("  点位数量: %d" % len(points))
for i, p in enumerate(points):
    d = p.to_dict() if hasattr(p, "to_dict") else p
    if isinstance(d, dict):
        keep = {k: d.get(k) for k in
                ("pointName", "name", "lat", "lon", "lng", "glat", "glon",
                 "isFixed", "id", "position") if k in d}
        print("  [%d] %s" % (i, json.dumps(keep, ensure_ascii=False)))
        rest = {k: v for k, v in d.items() if k not in keep}
        if rest:
            print("       其余: %s" % json.dumps(rest, ensure_ascii=False, default=str)[:200])
    else:
        print("  [%d] %r" % (i, d))
if getattr(cli.policy, "last_checkpoint_error", None):
    print("  错误:", cli.policy.last_checkpoint_error)
print("  area_id:", getattr(cli.policy, "last_checkpoint_area_id", None))
