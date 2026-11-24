# -*- coding: utf-8 -*-
"""围栏回显对拍：把我们生成的 geoFencesJson 与真机 PASS 样本逐字段比对。

真机基准来自 obs_PASS_*.json 的 fixed_point_json.geoFencesJson。
本脚本不联网。
"""
from __future__ import annotations

import gzip
import base64
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from running.builder import build_geo_fences_json      # noqa: E402

# 服务端**下发**的围栏原始形态（顶点字段是 glon/lon + pointsNumber）。
# 顶点坐标取自真机 PASS 样本回传值的逆推：回传 glat/glng 与下发 glat/glon
# 是同一组数，只在字段名上不同（glon→glng、lon→lng）并去掉 pointsNumber。
LIVE_RAW = {
    "id": 1922,
    "name": "围栏2",
    "points": [
        {"lon": 0.0, "lat": 0.0, "glon": 113.384973, "glat": 23.342203, "pointsNumber": 1},
        {"lon": 0.0, "lat": 0.0, "glon": 113.384383, "glat": 23.341487, "pointsNumber": 2},
        {"lon": 0.0, "lat": 0.0, "glon": 113.384735, "glat": 23.340228, "pointsNumber": 3},
        {"lon": 0.0, "lat": 0.0, "glon": 113.385177, "glat": 23.340207, "pointsNumber": 4},
        {"lon": 0.0, "lat": 0.0, "glon": 113.385886, "glat": 23.340211, "pointsNumber": 5},
        {"lon": 0.0, "lat": 0.0, "glon": 113.385663, "glat": 23.341880, "pointsNumber": 6},
        {"lon": 0.0, "lat": 0.0, "glon": 113.385663, "glat": 23.341880, "pointsNumber": 7},
        {"lon": 0.0, "lat": 0.0, "glon": 113.385601, "glat": 23.341932, "pointsNumber": 8},
    ],
}


class _Fence:
    """最小围栏对象：只提供 builder 需要的 raw / fence_id / fence_name。"""
    def __init__(self, raw):
        self.raw = raw
        self.fence_id = raw.get("id")
        self.fence_name = raw.get("name")


def unbox(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.loads(gzip.decompress(base64.b64decode(value)))
    except Exception:
        return None


def real_reference() -> list:
    """从真机 PASS 样本取 geoFencesJson 作为基准。"""
    for name in ("obs_PASS_1331722339.json", "obs_PASS_1333728921.json"):
        path = os.path.join(BASE, name)
        if not os.path.exists(path):
            continue
        d = json.loads(open(path, encoding="utf-8").read())
        fp = unbox(d.get("fixed_point_json") or "")
        if not isinstance(fp, dict):
            continue
        g = fp.get("geoFencesJson")
        if isinstance(g, str):
            try:
                g = json.loads(g)
            except Exception:
                continue
        if isinstance(g, list) and g:
            return g
    return []


def main() -> int:
    ref = real_reference()
    ours_json = build_geo_fences_json([_Fence(LIVE_RAW)])
    ours = json.loads(ours_json)

    print("=" * 78)
    print("围栏回显对拍")
    print("=" * 78)
    print("  真机基准:", "取到 %d 条围栏" % len(ref) if ref else "本地无 PASS 样本，仅做结构自检")
    print("  我们生成: %d 条围栏，%d 字符" % (len(ours), len(ours_json)))
    print()

    bad = 0

    def check(name, ok, expect, got):
        nonlocal bad
        if not ok:
            bad += 1
        print("  [%s] %-22s 期望 %-28s 实际 %s" % (
            "OK " if ok else "BAD", name, str(expect)[:28], str(got)[:40]))

    check("围栏条目数", len(ours) == (len(ref) if ref else 1),
          len(ref) if ref else 1, len(ours))
    if not ours:
        print("  生成结果为空，无法继续")
        return 1

    o = ours[0]
    check("条目 keys", list(o.keys()) == ["distance", "id", "name", "points"],
          ["distance", "id", "name", "points"], list(o.keys()))
    check("distance", o.get("distance") == 0.0, 0.0, o.get("distance"))
    check("id", o.get("id") == 1922, 1922, o.get("id"))
    check("name 未转义", "围栏2" in ours_json and "\\u" not in ours_json,
          "围栏2 原文", o.get("name"))
    pts = o.get("points") or []
    check("顶点数", len(pts) == 8, 8, len(pts))
    if pts:
        check("顶点 keys", list(pts[0].keys()) == ["glat", "glng", "lat", "lng"],
              ["glat", "glng", "lat", "lng"], list(pts[0].keys()))
        check("顶点含 glng", "glng" in pts[0], "有", "有" if "glng" in pts[0] else "无")
        check("顶点无 glon", "glon" not in pts[0], "无", "无" if "glon" not in pts[0] else "有")
        check("顶点无 pointsNumber", "pointsNumber" not in pts[0],
              "无", "无" if "pointsNumber" not in pts[0] else "有")
        check("glat 首点", abs(pts[0]["glat"] - 23.342203) < 1e-9,
              23.342203, pts[0]["glat"])
        check("glng 首点", abs(pts[0]["glng"] - 113.384973) < 1e-9,
              113.384973, pts[0]["glng"])

    # 与真机逐字段比对
    if ref:
        r = ref[0]
        print()
        print("  ── 与真机逐字段比对 ──")
        check("真机条目 keys 一致", list(o.keys()) == list(r.keys()),
              list(r.keys()), list(o.keys()))
        if pts and r.get("points"):
            check("真机顶点 keys 一致",
                  list(pts[0].keys()) == list(r["points"][0].keys()),
                  list(r["points"][0].keys()), list(pts[0].keys()))
            same = all(
                abs(float(a.get("glat", 0)) - float(b.get("glat", 0))) < 1e-9
                and abs(float(a.get("glng", 0)) - float(b.get("glng", 0))) < 1e-9
                for a, b in zip(pts, r["points"])
            )
            check("全部顶点坐标一致", same, "逐点相同", "相同" if same else "有差异")

    print()
    print("=" * 78)
    if bad == 0:
        print("结论：围栏回显与真机形态一致")
    else:
        print("结论：%d 项不一致" % bad)
    print("=" * 78)
    print()
    print("生成的 geoFencesJson 前 300 字符：")
    print(" ", ours_json[:300])
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
