# -*- coding: utf-8 -*-
"""DRY-RUN —— 走完真实链路的阶段 1/2/3（拉规则、风控预检、生成报文、本地自检），
**不进入阶段 4/5**，也就是不等待、不上传 OBS、不提交成绩。

这是 `--run` 去掉最后两步的等价物，报文与真提交时**逐字节相同**
（同一个 `_prepare_track` 产出）。打印全部关键指标供人工核对。

用法::

    python dry_run.py                      # 默认 2000m / 660s
    python dry_run.py --distance 2000 --time 660
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
import os
import statistics
import sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")

from sport_client import SportClient792                     # noqa: E402
from core.session import load_session                        # noqa: E402
from config_loader import get_session_file_path              # noqa: E402
from running.client import RunningClient                     # noqa: E402
from running.consistency import distance                     # noqa: E402


def unbox(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.loads(gzip.decompress(base64.b64decode(value)))
    except Exception:
        return None


def sph_length(points):
    total = 0.0
    for a, b in zip(points, points[1:]):
        la1, la2 = math.radians(a["gLat"]), math.radians(b["gLat"])
        d = math.radians(b["gLng"] - a["gLng"])
        c = (math.sin(la1) * math.sin(la2)
             + math.cos(la1) * math.cos(la2) * math.cos(d))
        total += 6371000 * math.acos(max(-1.0, min(1.0, c)))
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description="运动世界校园 干跑（不提交）")
    ap.add_argument("--distance", type=int, default=2000)
    ap.add_argument("--time", type=int, default=660)
    ap.add_argument("--mode", type=int, default=1, choices=[1, 6])
    ap.add_argument("--no-realism", action="store_true")
    args = ap.parse_args()

    sess = load_session(get_session_file_path())
    if not sess:
        print("没有缓存凭据，先登录"); return 1
    cli = SportClient792(uid=sess.get("uid"), token=sess.get("token"),
                         unid=sess.get("unid"))
    runner = RunningClient(uid=sess.get("uid"), token=sess.get("token"),
                           unid=sess.get("unid"))

    logs = []
    def log(msg):
        logs.append(str(msg))
        print("  [链路] %s" % msg)

    print("=" * 82)
    print("阶段 1/5  拉规则 · 校时钟 · 取围栏与打卡点")
    print("=" * 82)
    setup, bad = runner._prepare_run(args.mode, args.distance, args.time, log)
    if bad is not None or setup is None:
        print("  ✗ 中止:", getattr(bad, "message", "未知"))
        return 1

    print()
    print("=" * 82)
    print("阶段 2/5  风控预检（无副作用）")
    print("=" * 82)
    runner._risk_preflight(setup, log)

    print()
    print("=" * 82)
    print("阶段 3/5  生成轨迹 · 组装报文 · 本地自检")
    print("=" * 82)
    track, bad = runner._prepare_track(
        setup, args.mode, args.distance, args.time,
        realism=not args.no_realism, log=log)
    if bad is not None or track is None:
        print("  ✗ 中止:", getattr(bad, "message", "未知"))
        return 1

    print()
    print("=" * 82)
    print("★ 此处本应进入阶段 4（物理等待）与阶段 5（上传+提交）—— 已跳过")
    print("=" * 82)

    # ------------------------------------------------------------------ 报文解析
    save = track.save_record
    obs = track.obs_payload
    loc = unbox(obs["run_data"])
    pj = json.loads(loc) if isinstance(loc, str) else loc
    seg = unbox(obs["segment_json"])
    seg = json.loads(seg) if isinstance(seg, str) else (seg or [])
    laps = unbox(obs["laps_json"])
    laps = json.loads(laps) if isinstance(laps, str) else (laps or [])
    env = json.loads(save["fivePointJson"])
    fp = json.loads(env["fivePointJson"])

    n = len(pj)
    flags = {p["flag"] for p in pj}
    counts = sorted({p["count"] for p in pj})
    queues = sorted({p["queueNum"] for p in pj})
    radii = [p["radius"] for p in pj]
    hav = sum(distance((a["gLat"], a["gLng"]), (b["gLat"], b["gLng"]))
              for a, b in zip(pj, pj[1:]))
    sp = sph_length(pj)
    tdisp = [p["totalTime"] for p in pj]
    speeds = []
    for a, b in zip(pj, pj[1:]):
        dt = b["totalTime"] - a["totalTime"]
        if dt > 0:
            speeds.append(distance((a["gLat"], a["gLng"]),
                                   (b["gLat"], b["gLng"])) / dt)
    cp_dist = []
    for c in setup.checkpoints:
        glat = float(c.get("glat", c.get("lat")))
        glon = float(c.get("glon", c.get("glng", c.get("lng", c.get("lon")))))
        cp_dist.append(min(distance((p["gLat"], p["gLng"]), (glat, glon)) for p in pj))

    # 围栏内判定
    poly = setup.fence_polygon or []
    inside = None
    if poly and len(poly) >= 3:
        from running.geometry import point_in_polygon
        inside = sum(1 for p in pj if point_in_polygon((p["gLat"], p["gLng"]), poly))

    print()
    print("=" * 82)
    print("报文指标核对")
    print("=" * 82)
    print("  ── 轨迹 ──")
    print("  轨迹点数            %d" % n)
    print("  点字段数            %d   %s" % (len(pj[0]), "✓" if len(pj[0]) == 27 else "✗"))
    print("  flag 唯一值          %d   %s" % (len(flags), "✓" if len(flags) == 1 else "✗"))
    print("  count 取值          %s" % counts)
    print("  queueNum            %d 个不同值 (范围 %d..%d)" % (len(queues), queues[0], queues[-1]))
    print("  radius              %.3f ~ %.3f   %s" % (
        min(radii), max(radii), "✓" if max(radii) <= 3.2 else "✗"))
    print("  state 取值          %s" % sorted({p["state"] for p in pj}))
    print("  stepDistance 唯一值  %s" % sorted({p["stepDistance"] for p in pj}))
    print("  coorType            %s" % sorted({p["coorType"] for p in pj}))
    print("  ── 里程与时间 ──")
    print("  里程 haversine      %.4f  (偏差 %+.4f)" % (hav, hav - args.distance))
    print("  里程 球面余弦        %.4f  (偏差 %+.4f)" % (sp, sp - args.distance))
    print("  累计时间末值         %d s   %s" % (tdisp[-1], "✓" if tdisp[-1] == args.time else "✗"))
    print("  瞬时速度 max        %.2f m/s   %s" % (max(speeds), "✓" if max(speeds) < 8 else "✗"))
    print("  ── 打卡点 ──")
    print("  打卡点数            %d" % len(fp))
    print("  最近距离            %s" % [round(x, 4) for x in cp_dist])
    print("    max               %.4f m   %s" % (max(cp_dist), "✓" if max(cp_dist) < 10 else "✗"))
    print("  position            %s" % [p["position"] for p in fp])
    print("  isFixed             %s" % [p["isFixed"] for p in fp])
    print("  isPass              %s" % [p["isPass"] for p in fp])
    print("  ── 分段与圈 ──")
    print("  segment_json 段数    %d  (首段 id=%s)" % (
        len(seg), seg[0]["id"] if seg else "-"))
    print("  laps_json 圈数       %d" % len(laps))
    print("  type 分布           %s" % dict(Counter(p["type"] for p in pj)))
    print("  ── 围栏回显 ──")
    gf_raw = env.get("geoFencesJson") or "[]"
    try:
        gf = json.loads(gf_raw)
    except Exception:
        gf = []
    print("  geoFencesJson 长度   %d 字符" % len(gf_raw))
    print("  含转义序列           %s   %s" % (
        "\\u" in gf_raw, "✗ 真机是 UTF-8 原文" if "\\u" in gf_raw else "✓"))
    print("  围栏条目数           %d   %s" % (len(gf), "✓" if gf else "✗ 空"))
    for g in gf:
        pts = g.get("points") or []
        print("    id=%s  name=%r  顶点=%d" % (g.get("id"), g.get("name"), len(pts)))
        if pts:
            print("      首顶点 %s" % json.dumps(pts[0], ensure_ascii=False))
    print("  ── runAreaId 两处 ──")
    print("  envelope.runAreaId   %s   %s" % (
        env.get("runAreaId"), "✓（真机 -1）" if env.get("runAreaId") == -1 else "✗"))
    print("  save_record.runAreaId %s   %s" % (
        save.get("runAreaId"),
        "✓（真实围栏 id）" if save.get("runAreaId") == (gf[0].get("id") if gf else None) else "✗"))
    print("  save_record.geoFenceJson %s" % (
        ("%d 字符" % len(save["geoFenceJson"])) if "geoFenceJson" in save else "未设置"))
    print("  ── 结算字段 ──")
    print("  save_record.speed   %.3f 分/公里" % (save["speed"] / 1000))
    print("  save_record.totalDis %s" % save["totalDis"])
    print("  save_record.totalTime %s" % save["totalTime"])
    print("  save_record.totalSteps %s" % save["totalSteps"])
    print("  save_record.avgStepFreq %s" % save["avgStepFreq"])
    print("  save_record.calorie  %s" % save["calorie"])
    print("  save_record.complete %s" % save["complete"])
    print("  save_record.policy   %s" % save["policy"])
    print("  save_record.runAreaId %s" % save["runAreaId"])
    print("  save_record.selDistance %s" % save["selDistance"])
    print("  segmentJson 长度     %d 字符" % len(save["segmentJson"]))
    print("  allLocJson 长度      %d 字符" % len(save["allLocJson"]))
    print("  OBS object_key      %s" % track.object_key)

    # ---------------------------------------------------------------- 判定
    print()
    print("=" * 82)
    print("对照实时规则判定")
    print("=" * 82)
    rule_raw = setup.rule.raw.get("runRuleModel") or {}
    checks = []
    checks.append(("单次最低里程", rule_raw.get("minDistance", 0),
                   args.distance, args.distance >= rule_raw.get("minDistance", 0)))
    checks.append(("最短时长达标", rule_raw.get("minRunTime", 0),
                   args.time, args.time >= rule_raw.get("minRunTime", 0)))
    pace = (args.time / 60.0) / (args.distance / 1000.0)
    lo = rule_raw.get("speedTop", 0); hi = rule_raw.get("speedBottom", 99)
    checks.append(("平均配速在区间", "%.1f~%.1f 分/km" % (lo, hi),
                   "%.3f" % pace, lo <= pace <= hi))
    stepfreq = save["avgStepFreq"]
    checks.append(("平均步频在区间",
                   "%d~%d" % (rule_raw.get("stepBottom", 0), rule_raw.get("stepTop", 999)),
                   stepfreq,
                   rule_raw.get("stepBottom", 0) <= stepfreq <= rule_raw.get("stepTop", 999)))
    checks.append(("打卡点全部经过", "最近距离 <10m",
                   "%.4fm" % max(cp_dist), max(cp_dist) < 10))
    checks.append(("position 连续", "0..%d" % (len(fp) - 1),
                   str([p["position"] for p in fp]),
                   [p["position"] for p in fp] == list(range(len(fp)))))
    checks.append(("轨迹在围栏内", "全部点",
                   "%s/%s" % (inside, n) if inside is not None else "无围栏",
                   inside == n if inside is not None else True))
    fence_id = gf[0].get("id") if gf else None
    checks.append(("geoFencesJson 非空", "含围栏 id",
                   "id=%s" % fence_id, bool(gf) and fence_id is not None))
    checks.append(("geoFencesJson 非转义", "UTF-8 原文",
                   "有 \\u" if "\\u" in gf_raw else "无 \\u", "\\u" not in gf_raw))
    checks.append(("envelope.runAreaId", "-1",
                   str(env.get("runAreaId")), env.get("runAreaId") == -1))
    checks.append(("顶层.runAreaId", "= 围栏 id %s" % fence_id,
                   str(save.get("runAreaId")),
                   fence_id is not None and save.get("runAreaId") == fence_id))
    bad = 0
    for name, expect, got, ok in checks:
        if not ok:
            bad += 1
        print("  [%s] %-16s 期望 %-22s 实际 %s" % (
            "OK " if ok else "BAD", name, expect, got))

    print()
    print("=" * 82)
    if bad == 0:
        print("结论：全部合格。报文已生成但**未提交**。")
    else:
        print("结论：%d 项不合格，不要提交。" % bad)
    print("=" * 82)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
