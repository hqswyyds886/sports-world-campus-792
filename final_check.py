# -*- coding: utf-8 -*-
"""最终事实核查 —— 直接打印一份真实参数下的报文关键指标，不依赖任何测试断言。

用途：提交前人工过一遍，确认每一栏都落在「真机 PASS 样本」的实测区间里。
不联网、不提交。
"""
from __future__ import annotations

import base64
import gzip
import json
import math
import os
import random
import statistics
import sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from running.builder import RunningTrackBuilder      # noqa: E402
from running import pass_form                        # noqa: E402
from running.consistency import distance             # noqa: E402

# 该学校真实打卡点（GCJ-02，来自 --checkpoints 实测）
CHECKPOINTS = [
    {"glat": 23.341507, "glon": 113.384641, "lat": 23.347743, "lon": 113.391091,
     "pointName": "田径场2", "isFixed": 0},
    {"glat": 23.340726, "glon": 113.385437, "lat": 23.346972, "lon": 113.391886,
     "pointName": "田径场5", "isFixed": 0},
    {"glat": 23.340453, "glon": 113.385033, "lat": 23.346694, "lon": 113.391483,
     "pointName": "田径场1", "isFixed": 0},
    {"glat": 23.340934, "glon": 113.384717, "lat": 23.347171, "lon": 113.391167,
     "pointName": "田径场3", "isFixed": 1},
    {"glat": 23.340812, "glon": 113.384955, "lat": 23.347049, "lon": 113.391405,
     "pointName": "田径场6", "isFixed": 0},
]

FENCE = [(23.33950, 113.38380), (23.33950, 113.38620),
         (23.34260, 113.38620), (23.34260, 113.38380)]


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


def run_case(distance_m, time_sec, steps, label):
    rng = random.Random(20261124)
    builder = RunningTrackBuilder(
        uid=16620891, unid=122301, sport_type=1,
        uuid_str="11111111-2222-3333-4444-555555555555", rng=rng)
    center_lat = sum(c["glat"] for c in CHECKPOINTS) / len(CHECKPOINTS)
    center_lng = sum(c["glon"] for c in CHECKPOINTS) / len(CHECKPOINTS)
    start_ms = 1791884216857

    pts, five = builder.generate_track_around_points(
        center_lat=center_lat, center_lng=center_lng,
        checkpoints=CHECKPOINTS,
        total_distance_m=distance_m, total_time_sec=time_sec,
        start_time_ms=start_ms, fence_polygon=FENCE)
    stop_ms = start_ms + time_sec * 1000
    save, obs, key = builder.build_submission_payload(
        total_distance_m=distance_m, total_time_sec=time_sec,
        total_steps=steps, start_time_ms=start_ms, stop_time_ms=stop_ms,
        gps_points=pts, five_points=five,
        sel_distance_m=2000, sel_run_time_s=600, policy=1,
        run_area_id=1668, geo_fences_json="[]", total_ascent=5)

    loc = unbox(obs["run_data"])
    pj = json.loads(loc) if isinstance(loc, str) else loc
    seg = unbox(obs["segment_json"])
    seg = json.loads(seg) if isinstance(seg, str) else (seg or [])
    laps = unbox(obs["laps_json"])
    laps = json.loads(laps) if isinstance(laps, str) else (laps or [])
    env = json.loads(save["fivePointJson"])
    fp = json.loads(env["fivePointJson"])

    # 指标
    n = len(pj)
    flags = {p["flag"] for p in pj}
    counts = sorted({p["count"] for p in pj})
    queues = sorted({p["queueNum"] for p in pj})
    radii = [p["radius"] for p in pj]
    hav = sum(distance((a["gLat"], a["gLng"]), (b["gLat"], b["gLng"]))
              for a, b in zip(pj, pj[1:]))
    sp = sph_length(pj)
    tdisp = [p["totalTime"] for p in pj]
    gaps = [t - s for s, t in zip(tdisp, tdisp[1:]) if t > s]
    speeds = []
    for a, b in zip(pj, pj[1:]):
        dt = (b["totalTime"] - a["totalTime"])
        dd = distance((a["gLat"], a["gLng"]), (b["gLat"], b["gLng"]))
        if dt > 0:
            speeds.append(dd / dt)
    with_speed = [p["avgSpeed"] for p in pj if p["avgSpeed"] > 0]
    cp_dist = []
    for c in CHECKPOINTS:
        cp_dist.append(min(distance((p["gLat"], p["gLng"]),
                                    (c["glat"], c["glon"])) for p in pj))

    print("=" * 80)
    print(f"{label}   {distance_m}m / {time_sec}s / {steps}步")
    print("=" * 80)
    print(f"  轨迹点数            {n}")
    print(f"  点字段数            {len(pj[0])}   {'✓' if len(pj[0]) == 27 else '✗'}")
    print(f"  flag 唯一值         {len(flags)}   {'✓' if len(flags) == 1 else '✗'}")
    print(f"  count 取值          {counts}")
    print(f"  queueNum 唯一个数   {len(queues)}  (范围 {queues[0]}..{queues[-1]})")
    print(f"  radius 范围         {min(radii):.3f} ~ {max(radii):.3f}   "
          f"{'✓' if max(radii) <= 3.1 + 1e-6 else '✗'}")
    print(f"  里程 haversine      {hav:.4f}  (偏差 {hav - distance_m:+.4f})")
    print(f"  里程 球面余弦       {sp:.4f}  (偏差 {sp - distance_m:+.4f})")
    print(f"  累计时间间隔        min={min(gaps)}s max={max(gaps)}s 中位={statistics.median(gaps):.0f}s")
    print(f"  瞬时速度 max        {max(speeds):.2f} m/s   {'✓' if max(speeds) < 8 else '✗'}")
    print(f"  avgSpeed 范围       {min(with_speed):.2f} ~ {max(with_speed):.2f} m/s")
    print(f"  打卡点最近距离      {[round(x, 4) for x in cp_dist]}")
    print(f"    max               {max(cp_dist):.4f} m   {'✓' if max(cp_dist) < 10 else '✗'}")
    print(f"  position 序号       {[p['position'] for p in fp]}")
    print(f"    isFixed           {[p['isFixed'] for p in fp]}")
    print(f"  segment_json 段数   {len(seg)}   (首段 id={seg[0]['id'] if seg else '-'})")
    print(f"  laps_json 圈数      {len(laps)}")
    print(f"  save_record.speed   {save['speed']/1000:.3f} 分/公里")
    print(f"  save_record.segment 长度 {len(save['segmentJson'])} 字符")
    print(f"  allLocJson 长度     {len(save['allLocJson'])} 字符")
    print(f"  OBS object_key      {key}")
    print(f"  type 分布           {dict(Counter(p['type'] for p in pj))}")
    print()

    # 与 PASS 样本区间对照
    #
    # 阈值的取法说明（别写成死值，会误报）：
    #   · queueNum 是「唯一值个数」，PASS 两条样本分别是 24 / 23 个，覆盖 0..23。
    #     这里要求 ≥22 且 ≤24（按序号取模，超出 24 说明模数错了）。
    #   · laps 圈数由里程决定：2150m → 3 圈（2 整圈 + 收尾），2000m → 2 圈。
    #     要求 round(里程/1000) 与实际一致。
    #   · segment 段数 = ceil(总时长/30)，PASS 样本 663s → 23 段（末段 3s），
    #     760s → 26 段。要求与公式一致。
    expect_laps = int(math.ceil(distance_m / 1000.0))
    expect_seg = int(math.ceil(time_sec / float(pass_form.SEGMENT_SEC)))
    ref = [
        ("点字段数", 27, 27, len(pj[0])),
        ("radius 上限", 1.5, 4.25, max(radii)),
        ("queueNum 覆盖", 22, 24, len(queues)),
        ("瞬时速度上限", 0.0, 8.0, max(speeds)),
        ("segment 段数", expect_seg, expect_seg, len(seg)),
        ("laps 圈数", expect_laps, expect_laps, len(laps)),
        ("position 起点", 0, 0, fp[0]["position"]),
        ("position 连续", 0, 4, fp[-1]["position"]),
    ]
    print("  与 PASS 样本区间对照：")
    bad = 0
    for name, lo, hi, got in ref:
        ok = lo - 1e-9 <= got <= hi + 1e-9
        if not ok:
            bad += 1
        print(f"    [{'OK ' if ok else 'BAD'}] {name:<16} 期望 {lo}..{hi}  实际 {got}")
    print()
    return bad


def main():
    bad = 0
    bad += run_case(2000, 660, 1650, "场景 A：2 公里 / 11 分钟")
    bad += run_case(2150, 760, 1800, "场景 B：2.15 公里 / 12.7 分钟")
    print("=" * 80)
    if bad == 0:
        print("结论：全部指标落在真机 PASS 样本区间内")
    else:
        print(f"结论：{bad} 项越界")
    print("=" * 80)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
