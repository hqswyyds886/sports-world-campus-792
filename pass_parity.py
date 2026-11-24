# -*- coding: utf-8 -*-
"""离线对拍 —— 本地生成的报文 vs 服务端真实 PASS 样本。

不联网、不提交。逐字段比对统计特征，任何一项超出容差就 FAIL。

用法::

    python pass_parity.py            # 全部用例
    python pass_parity.py --verbose  # 打印逐字段明细
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import statistics
import sys
from collections import Counter
from typing import Any, Dict, List, Tuple

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from running.builder import RunningTrackBuilder            # noqa: E402
from running import pass_form                              # noqa: E402

# ---------------------------------------------------------------------------
# 真实 PASS 样本
# ---------------------------------------------------------------------------

PASS_FILES = ["obs_PASS_1000000015.json", "obs_PASS_1000000018.json"]


def unbox(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.loads(gzip.decompress(base64.b64decode(value)))
    except Exception:
        return None


def load_pass_sample(name: str) -> Dict[str, Any]:
    """解出一条真实 PASS 记录的 run_data / segment / laps / fixed_point。

    `run_data` 是对象 `{"allLocJson": "...", "useZip": false}`（真机形态），
    点数组在 `allLocJson` 里。旧版本这里直接把 run_data 当数组用，
    真机样本一进来就崩。
    """
    raw = json.loads(open(os.path.join(BASE, name), encoding="utf-8").read())
    run_data = unbox(raw.get("run_data") or "") or {}
    if isinstance(run_data, dict):
        loc = run_data.get("allLocJson")
        points = json.loads(loc) if isinstance(loc, str) else (loc or [])
    else:
        # 容错：早期样本或已归一化的裸数组
        points = run_data if isinstance(run_data, list) else []
    return {
        "name": name,
        "points": points,
        "segment": unbox(raw.get("segment_json") or "") or [],
        "laps": unbox(raw.get("laps_json") or "") or [],
        "fixed_point": unbox(raw.get("fixed_point_json") or "") or {},
    }


def profile_points(points: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把一串点压成可比较的统计画像。"""
    if not points:
        return {}
    n = len(points)

    def nums(key):
        return [float(p[key]) for p in points
                if key in p and isinstance(p[key], (int, float)) and not isinstance(p[key], bool)]

    def uniq(key):
        return len(set(str(p.get(key)) for p in points))

    def rng(key):
        v = nums(key)
        return (min(v), max(v)) if v else (None, None)

    def monotonic(key) -> bool:
        v = nums(key)
        return all(b >= a - 1e-9 for a, b in zip(v, v[1:]))

    type_dist = dict(Counter(p.get("type") for p in points))
    count_vals = sorted(set(p.get("count") for p in points))
    queue_vals = sorted(set(p.get("queueNum") for p in points))
    state_vals = sorted(set(p.get("state") for p in points))
    radius_lo, radius_hi = rng("radius")

    return {
        "n": n,
        "field_count": len(points[0]),
        "fields": list(points[0].keys()),
        "count_values": count_vals,
        "count_uniq": len(count_vals),
        "queue_range": (queue_vals[0], queue_vals[-1]) if queue_vals else (None, None),
        "queue_uniq": len(queue_vals),
        "state_values": state_vals,
        "radius_range": (radius_lo, radius_hi),
        "stepDistance_uniq": uniq("stepDistance"),
        "lat_uniq": sorted(set(p.get("lat") for p in points))[:3],
        "lng_uniq": sorted(set(p.get("lng") for p in points))[:3],
        "totalDis_mono": monotonic("totalDis"),
        "validDis_mono": monotonic("validDis"),
        "totalTime_mono": monotonic("totalTime"),
        "type_dist": type_dist,
        "coorType_values": sorted(set(p.get("coorType") for p in points)),
        "bdG_values": sorted(set(p.get("bdG") for p in points)),
        "dtr_values": sorted(set(p.get("dtr") for p in points)),
        "locType_values": sorted(set(p.get("locType") for p in points)),
        "bds_min": rng("bdS")[0],
        "bds_zero_count": sum(1 for p in points if float(p.get("bdS") or 0) == 0.0),
        "bdD_uniq": uniq("bdD"),
        "flag_uniq": uniq("flag"),
        "avgSpeed_max": rng("avgSpeed")[1],
        "speed_max": rng("speed")[1],
        "gainTime_uniq": uniq("gainTime"),
        "id_range": rng("id"),
    }


# ---------------------------------------------------------------------------
# 本地生成
# ---------------------------------------------------------------------------

#: 和 PASS 样本同量级的参数（2000m / 660s）
CASE = dict(distance_m=2008, time_sec=663, steps=1653)

#: 该学校真实打卡点（GCJ-02，从 --checkpoints 拉到）
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

#: 围栏（该学校 1 个围栏，中心取打卡点质心）
FENCE = [
    (23.33950, 113.38380), (23.33950, 113.38620),
    (23.34260, 113.38620), (23.34260, 113.38380),
]


def build_local() -> Dict[str, Any]:
    """离线生成一份提交报文（不联网）。"""
    import random

    rng = random.Random(20261124)
    builder = RunningTrackBuilder(
        uid=10000001, unid=100001, sport_type=1,
        uuid_str="11111111-2222-3333-4444-555555555555", rng=rng)

    center_lat = sum(c["glat"] for c in CHECKPOINTS) / len(CHECKPOINTS)
    center_lng = sum(c["glon"] for c in CHECKPOINTS) / len(CHECKPOINTS)

    start_ms = 1791884216857  # 与 PASS 样本同时段（17:36 起跑）
    points, five = builder.generate_track_around_points(
        center_lat=center_lat, center_lng=center_lng,
        checkpoints=CHECKPOINTS,
        total_distance_m=CASE["distance_m"],
        total_time_sec=CASE["time_sec"],
        start_time_ms=start_ms,
        fence_polygon=FENCE,
    )
    stop_ms = start_ms + CASE["time_sec"] * 1000

    save_record, obs_payload, object_key = builder.build_submission_payload(
        total_distance_m=CASE["distance_m"],
        total_time_sec=CASE["time_sec"],
        total_steps=CASE["steps"],
        start_time_ms=start_ms,
        stop_time_ms=stop_ms,
        gps_points=points,
        five_points=five,
        sel_distance_m=2000,
        sel_run_time_s=600,
        policy=1,
        run_area_id=1668,
        geo_fences_json="[]",
        total_ascent=5,
        physio={"avgPower": 223},
        jitter_buckets=True,
    )
    return {
        "save_record": save_record,
        "obs_payload": obs_payload,
        "object_key": object_key,
        "points": points,
        "five": five,
        "start_ms": start_ms,
    }


# ---------------------------------------------------------------------------
# 对拍规则
# ---------------------------------------------------------------------------

class Check:
    def __init__(self, name: str, ok: bool, expected: Any, actual: Any, note: str = ""):
        self.name = name
        self.ok = ok
        self.expected = expected
        self.actual = actual
        self.note = note


def in_range(value, lo, hi, tol=0.0):
    if value is None:
        return False
    return (lo - tol) <= value <= (hi + tol)


def compare(local: Dict[str, Any], ref: Dict[str, Any]) -> List[Check]:
    """把本地报文与 PASS 样本画像逐项对拍。"""
    checks: List[Check] = []
    lp = local["gen_profile"]
    rp = ref["profile"]

    # ---- 1. 点结构
    checks.append(Check(
        "点字段数", lp["field_count"] == 27,
        "27", lp["field_count"]))
    checks.append(Check(
        "字段名完全一致", lp["fields"] == rp["fields"],
        "与 PASS 同序", "一致" if lp["fields"] == rp["fields"] else lp["fields"]))

    # ---- 2. position（最关键）
    positions = local["positions"]
    checks.append(Check(
        "fivePointJson position 连续 0..N-1",
        positions == list(range(len(positions))),
        list(range(len(positions))), positions))

    # ---- 3. count / queueNum / state
    checks.append(Check(
        "count 基线=10",
        lp["count_values"][0] == 10 and len(lp["count_values"]) <= 2,
        "以 10 为主", lp["count_values"]))
    checks.append(Check(
        "queueNum 覆盖 0..23",
        lp["queue_uniq"] >= 20,
        "≥20 个不同值", lp["queue_uniq"]))
    checks.append(Check(
        "state 恒 1", lp["state_values"] == [1],
        [1], lp["state_values"]))

    # ---- 4. radius 硬约束
    lo, hi = lp["radius_range"]
    checks.append(Check(
        "radius 落在 1.5~3.1", in_range(lo, 1.5, 3.1, 0.01) and in_range(hi, 1.5, 3.1, 0.01),
        "1.5~3.1", (round(lo, 4), round(hi, 4))))

    # ---- 5. 坐标系
    checks.append(Check(
        "lat/lng 恒 -1.0（占位）",
        lp["lat_uniq"] == [-1.0] and lp["lng_uniq"] == [-1.0],
        [-1.0], (lp["lat_uniq"], lp["lng_uniq"])))
    checks.append(Check(
        "coorType=gcj02", lp["coorType_values"] == ["gcj02"],
        ["gcj02"], lp["coorType_values"]))

    # ---- 6. 累计量单调
    checks.append(Check("totalDis 单调不减", lp["totalDis_mono"], True, lp["totalDis_mono"]))
    checks.append(Check("validDis 单调不减", lp["validDis_mono"], True, lp["validDis_mono"]))
    checks.append(Check("totalTime 单调不减", lp["totalTime_mono"], True, lp["totalTime_mono"]))

    # ---- 7. bdS 无 0 断点
    checks.append(Check(
        "bdS 无 0 值断点", lp["bds_zero_count"] <= max(3, int(lp["n"] * 0.01)),
        "≈0", lp["bds_zero_count"]))

    # ---- 8. bdD 离散化
    checks.append(Check(
        "bdD 唯一值 ≤10（离散朝向）", lp["bdD_uniq"] <= 10,
        f"PASS={rp['bdD_uniq']}", lp["bdD_uniq"]))

    # ---- 9. flag 全场同值
    checks.append(Check("flag 全场同值", lp["flag_uniq"] == 1, 1, lp["flag_uniq"]))

    # ---- 10. stepDistance 恒 0
    checks.append(Check("stepDistance 恒 0", lp["stepDistance_uniq"] == 1, 1, lp["stepDistance_uniq"]))

    # ---- 11. type 分布
    want_types = {0, 2, 3, 5, 6, 7}
    got_types = set(lp["type_dist"].keys())
    checks.append(Check(
        "type 覆盖 {0,2,3,5,6,7}", want_types.issubset(got_types),
        sorted(want_types), sorted(got_types)))
    checks.append(Check(
        "type=2 打卡点标记数 = 打卡点数",
        lp["type_dist"].get(2, 0) == len(local["positions"]),
        len(local["positions"]), lp["type_dist"].get(2, 0)))

    # ---- 12. 采样密度
    want_n = CASE["distance_m"] / pass_form.SAMPLE_STEP_M
    checks.append(Check(
        "采样点数接近 2.5m/点",
        abs(lp["n"] - want_n) / want_n <= 0.35,
        f"≈{int(want_n)}", lp["n"],
        note=f"PASS 样本 {rp['n']} 点"))

    # ---- 13. segment / laps 非空
    checks.append(Check(
        "segment_json 非空（PASS 有 23 段）", len(local["segments"]) >= 20,
        "≥20", len(local["segments"])))
    checks.append(Check(
        "laps_json 非空（PASS 有 3 圈）", len(local["laps"]) >= 2,
        "≥2", len(local["laps"])))

    # ---- 14. segment 首段 id == 段数（PASS 样本首段 id=23、共 23 段）
    seg_ok = bool(local["segments"]) and local["segments"][0].get("id") == len(local["segments"])
    checks.append(Check(
        "segment 首段 id == 段数", seg_ok,
        len(local["segments"]),
        local["segments"][0].get("id") if local["segments"] else None))

    # ---- 15. 圈自洽：步幅 × 步频 = pace
    lap_bad = 0
    for lap in local["laps"]:
        stride, cad, pace = lap.get("avgStride"), lap.get("avgCadence"), lap.get("avgPace")
        if not (stride and cad and pace):
            continue
        # cadence(步/分) * stride(m) / 1000 => km/min ; 配速 = 1 / 那个值
        implied = 1000.0 / (cad * stride / 100.0) if (cad * stride) > 0 else 0
        if implied > 0 and abs(implied - pace) / pace > 0.02:
            lap_bad += 1
    checks.append(Check(
        "圈表步幅×步频 与配速自洽", lap_bad == 0, 0, lap_bad))

    # ---- 16. save_record 关键字段
    sr = local["save_record"]
    checks.append(Check(
        "segmentJson 非空字符串", isinstance(sr.get("segmentJson"), str) and len(sr["segmentJson"]) > 10,
        "非空", str(sr.get("segmentJson"))[:20]))
    checks.append(Check(
        "speed 是配速（分/公里）", 4.0 <= float(sr.get("speed", 0)) / 1000.0 <= 12.0,
        "4~12", round(float(sr.get("speed", 0)) / 1000.0, 3)))

    return checks


def build_gen_profile(points_json: List[Dict[str, Any]]) -> Dict[str, Any]:
    return profile_points(points_json)


def _as_list(value) -> List[Any]:
    """unbox 出来的可能是已解析的 list，也可能是 JSON 字符串，统一成 list。"""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def run(verbose: bool = False) -> int:
    refs = [load_pass_sample(n) for n in PASS_FILES]
    local = build_local()

    # 本地生成的点（已序列化成 27 字段）
    run_data = unbox(local["obs_payload"]["run_data"])
    # run_data 是对象 {"allLocJson": "...", "useZip": false}，点数组在 allLocJson 里
    if isinstance(run_data, dict):
        loc = run_data.get("allLocJson")
        gen_points = json.loads(loc) if isinstance(loc, str) else (loc or [])
    else:
        gen_points = json.loads(run_data) if isinstance(run_data, str) else (run_data or [])
    local["gen_profile"] = build_gen_profile(gen_points)
    local["positions"] = [p.position for p in local["five"]]
    local["segments"] = _as_list(unbox(local["obs_payload"]["segment_json"]))
    local["laps"] = _as_list(unbox(local["obs_payload"]["laps_json"]))

    print("=" * 84)
    print("离线对拍 —— 本地生成 vs 服务端真实 PASS 样本")
    print("=" * 84)
    print(f"本地：{local['gen_profile']['n']} 点 / {len(local['segments'])} 段 / "
          f"{len(local['laps'])} 圈 / position={local['positions']}")
    for ref in refs:
        p = ref["profile"] = profile_points(ref["points"])
        print(f"参考 {ref['name']}: {p['n']} 点 / {len(ref['segment'])} 段 / "
              f"{len(ref['laps'])} 圈")
    print()

    total_fail = 0
    for ref in refs:
        ref["profile"] = profile_points(ref["points"])
        checks = compare(local, ref)
        fails = [c for c in checks if not c.ok]
        total_fail += len(fails)
        print(f"--- 对拍基准：{ref['name']} ---")
        for c in checks:
            mark = "PASS" if c.ok else "FAIL"
            line = f"  [{mark}] {c.name:<34} 期望={c.expected!r:<28} 实际={c.actual!r}"
            if c.note:
                line += f"  ({c.note})"
            if verbose or not c.ok:
                print(line)
        print(f"  小计：{len(checks) - len(fails)}/{len(checks)} 通过")
        print()

    print("=" * 84)
    if total_fail == 0:
        print("结论：全部通过 —— 报文形态已对齐 PASS 样本，可以进入提交验证")
    else:
        print(f"结论：{total_fail} 项未通过 —— 先修这些再提交")
    print("=" * 84)
    return 0 if total_fail == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="PASS 形态离线对拍")
    ap.add_argument("--verbose", action="store_true", help="打印全部检查项（含通过）")
    args = ap.parse_args()
    return run(verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
