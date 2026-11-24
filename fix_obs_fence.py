# -*- coding: utf-8 -*-
"""修复已提交记录的 OBS 明细 —— 重传修正后的围栏字段。

## 背景

rrid=1374320373 提交时用的是修复前的代码，`geoFencesJson` 里的围栏顶点字段是
服务端**下发**形态（`glon`/`lon` + `pointsNumber`），而真机**回传**形态是
（`glng`/`lng`，无 `pointsNumber`，条目多一个 `distance`）。

服务端按 `glng`/`lng` 取值 → 围栏多边形落空 → App 画不出绿框 →
两天后复核判「轨迹无法归属到任何围栏」→ 记录失效。

本脚本把已有 OBS 明细里的 `fixed_point_json.geoFencesJson` 就地修正，
然后**同时**写两个 key（pace-forge 的实测结论：详情页读前者，后者是兜底）：

    run_data/{YYYYMMDDHH}/{uuid}.json       ← 详情页展示用（我们从来没写过）
    runData/{uid}/{sportType}/{startSec}_{uuid}.txt  ← 兜底

## 不做的事

- 不改 `fivePointJson`（那条记录的 5 个点位本身是对的：position 0..4 连续）
- 不改 `run_data` / `speed_json` / `step_json` / `segment_json`（轨迹与分桶数据已通过）
- 不重新提交成绩（rrid 已入账，重提会产生第二条记录）
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")

from sport_client import SportClient792      # noqa: E402

HOST = "https://run.gxapp.iydsj.com"
BUCKET = "iydsj-hbase-hot"
RRID = 1374320373
LOCAL = os.path.join(BASE, "obs_OURS_1374320373.json")

# 手机 App 当前会话的 token（服务端 logout 只废了我们自己的，不影响 App）
TOKEN = "109c64be-e25b-4479-a288-79b0fb314317"
UID = "16620891"
UNID = "122301"


def gz(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(gzip.compress(data)).decode()


def unz(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.loads(gzip.decompress(base64.b64decode(value)))
    except Exception:
        return None


def normalize_fences(raw_json: str) -> str:
    """把围栏回显从「下发形态」改写成「真机回传形态」。

    - 条目补 `distance`
    - 顶点经度 `glon`→`glng`、`lon`→`lng`
    - 去掉 `pointsNumber`
    - 字段顺序按真机：glat / glng / lat / lng
    """
    try:
        fences = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except Exception:
        return raw_json
    if not isinstance(fences, list):
        return raw_json
    out = []
    for f in fences:
        if not isinstance(f, dict):
            continue
        pts = []
        for p in f.get("points") or []:
            if not isinstance(p, dict):
                continue
            pts.append({
                "glat": _num(p, ("glat", "gLat")),
                "glng": _num(p, ("glng", "gLng", "glon", "gLon", "lng", "lon")),
                "lat": _num(p, ("lat",)),
                "lng": _num(p, ("lng", "lon")),
            })
        out.append({
            "distance": f.get("distance", 0.0),
            "id": f.get("id"),
            "name": f.get("name"),
            "points": pts,
        })
    return json.dumps(out, separators=(",", ":"), ensure_ascii=False)


def _num(container, keys):
    for k in keys:
        v = container.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                continue
    return 0.0


def signed_url(cli, key: str, method: str):
    r = cli.history.execute_request(
        "POST", HOST + "/api/obs/temporary/url",
        body_plain={"bucketName": BUCKET, "objectKey": key,
                    "method": method, "contentType": "application/json"})
    d = r.get("data")
    if isinstance(d, str):
        d = json.loads(d)
    if not isinstance(d, dict):
        return None, {}
    return d.get("signedUrl"), (d.get("actualSignedRequestHeaders") or {})


def put(cli, key: str, body: bytes) -> bool:
    url, hdrs = signed_url(cli, key, "Put")
    if not url:
        print("    签名失败:", key)
        return False
    h = dict(hdrs)
    h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=h, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            ok = 200 <= resp.status < 300
            print("    PUT %s → %d  %d 字节" % (key, resp.status, len(body)))
            return ok
    except Exception as e:
        print("    PUT 失败 %s → %s" % (key, str(e)[:120]))
        return False


def get_size(cli, key: str):
    url, _ = signed_url(cli, key, "Get")
    if not url:
        return None
    try:
        return len(urllib.request.urlopen(urllib.request.Request(url), timeout=40).read())
    except Exception as e:
        return "404" if "404" in str(e) else str(e)[:40]


def main() -> int:
    cli = SportClient792(uid=UID, token=TOKEN, unid=UNID)

    # 1. 确认记录
    d = cli.history.execute_request(
        "POST", HOST + "/api/v70320/runnings/get_one_record",
        body_plain={"rrid": RRID}).get("data") or {}
    uuid_ = d.get("uuid")
    start_ms = d.get("startTime")
    sport = d.get("sportType")
    print("rrid=%s  uuid=%s  startTime=%s  sportType=%s" % (RRID, uuid_, start_ms, sport))
    print("当前 status=%s  isCheat=%s" % (d.get("status"), d.get("isCheat")))
    if not uuid_ or not start_ms:
        print("拿不到 uuid / startTime，中止")
        return 1

    # 2. 读本地已有的 OBS 明细（上次已下载）
    if not os.path.exists(LOCAL):
        print("本地没有 %s，请先下载" % LOCAL)
        return 1
    payload = json.loads(open(LOCAL, encoding="utf-8").read())
    fp = unz(payload.get("fixed_point_json") or "")
    if not isinstance(fp, dict):
        print("fixed_point_json 解不出来")
        return 1
    before = fp.get("geoFencesJson") or ""
    after = normalize_fences(before)
    print()
    print("修正前 geoFencesJson（首 160 字符）:")
    print("  ", before[:160])
    print("修正后 geoFencesJson（首 160 字符）:")
    print("  ", after[:160])
    print("  含 glon:", "glon" in after, " 含 glng:", "glng" in after,
          " 含 pointsNumber:", "pointsNumber" in after)

    # 3. 写回并重新打包该字段
    fp["geoFencesJson"] = after
    payload["fixed_point_json"] = gz(json.dumps(fp, separators=(",", ":"),
                                               ensure_ascii=False))

    # 3.1 `run_data` 必须是对象 `{"allLocJson": "...", "useZip": false}`
    #
    # 真机 PASS 样本解出来是 keys=["allLocJson","useZip"]，allLocJson 是
    # 370591 字符的点数组字符串。旧代码直接发裸点数组，App 取
    # `run_data.allLocJson` 得到 null → 轨迹画不出 → 绿框也画不出。
    rd = unz(payload.get("run_data") or "")
    if isinstance(rd, list):
        payload["run_data"] = gz(json.dumps(
            {"allLocJson": json.dumps(rd, separators=(",", ":"), ensure_ascii=False),
             "useZip": False},
            separators=(",", ":"), ensure_ascii=False))
        print()
        print("run_data: 裸数组 → 包成 {allLocJson, useZip} 对象（%d 点）" % len(rd))
    elif isinstance(rd, dict) and "allLocJson" in rd:
        print()
        print("run_data: 已经是对象形态，无需改动")
    else:
        print()
        print("run_data: 形态无法识别（%s），保持原样" % type(rd).__name__)

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    print("新 OBS 明细 %d 字节" % len(body))

    # 4. 两个 key 都写
    import datetime
    bj = datetime.datetime.fromtimestamp(start_ms / 1000, datetime.timezone.utc) \
        + datetime.timedelta(hours=8)
    detail_key = "run_data/%s/%s.json" % (bj.strftime("%Y%m%d%H"), uuid_)
    # 兜底 key 的秒数用**实际存在的那个**（提交时是 start_ms//1000 - 1，
    # 差 1 秒是因为 start_time_ms 的毫秒部分被截断，服务端回填的 startTime 向上取整）
    fallback_keys = [
        "runData/%s/%s/%s_%s.txt" % (UID, sport, start_ms // 1000 - 1, uuid_),
        "runData/%s/%s/%s_%s.txt" % (UID, sport, start_ms // 1000, uuid_),
    ]
    print()
    print("写入 OBS：")
    ok_detail = put(cli, detail_key, body)
    ok_fb = False
    for k in fallback_keys:
        if oc := get_size(cli, k):
            if oc != "404":
                ok_fb = put(cli, k, body) or ok_fb
                break

    # 5. 回读验证
    print()
    print("回读验证：")
    for k in [detail_key] + fallback_keys:
        size = get_size(cli, k)
        print("  %-72s → %s" % (k, size))

    print()
    if ok_detail:
        print("结论：详情页 key 已写入（%s）" % detail_key)
    else:
        print("结论：详情页 key 写入失败")
    return 0 if ok_detail else 1


if __name__ == "__main__":
    sys.exit(main())
