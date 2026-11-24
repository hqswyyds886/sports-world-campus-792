# -*- coding: utf-8 -*-
"""拉取通过 / 被判作弊记录的 OBS 轨迹明细，直接对比原始点位数据。

OBS 对象 key 约定（来自 pace-forge 逆向）：
  run_data/{YYYYMMDDHH}/{uuid}.json      （详情页展示用）
  runData/{uid}/{sportType}/{startTime}_{uuid}.txt  （兜底）
签名接口：POST /api/obs/temporary/url  {"bucketName","objectKey","method","contentType"}
注意 method 首字母大写：Put / Get
"""
import os, sys, json, datetime, urllib.request, urllib.parse

BASE = os.getcwd()
sys.path.insert(0, BASE)
os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")

from sport_client import SportClient792
from core.session import load_session
from config_loader import get_session_file_path

s = load_session(get_session_file_path())
cli = SportClient792(uid=s.get("uid"), token=s.get("token"), unid=s.get("unid"))

HOST = "https://run.gxapp.iydsj.com"
SIGN = HOST + "/api/obs/temporary/url"
BUCKET = "iydsj-hbase-hot"
UID = s.get("uid")


def signed(key, method="Get"):
    body = {"bucketName": BUCKET, "objectKey": key,
            "method": method, "contentType": "application/json"}
    try:
        return cli.history.execute_request("POST", SIGN, body_plain=body), None
    except Exception as e:
        return None, str(e)


def dl(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=40) as r:
            return r.read()
    except Exception as e:
        return None


def keys_for(uuid, start_ms, uid_, sport):
    # 服务端按北京时间切小时目录
    ts = start_ms / 1000
    cands = []
    for tzoff in (8, 0):
        dt = datetime.datetime.utcfromtimestamp(ts) + datetime.timedelta(hours=tzoff)
        for dh in (0, -1, 1):
            hh = dt + datetime.timedelta(hours=dh)
            tag = hh.strftime("%Y%m%d%H")
            cands.append("run_data/%s/%s.json" % (tag, uuid))
    cands.append("runData/%s/%s/%s_%s.txt" % (uid_, sport, start_ms, uuid))
    cands.append("runData/%s/%s/%s_%s.txt" % (uid_, sport, start_ms, uuid.upper()))
    # 去重保序
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


TARGETS = [(1333728921, "PASS"), (1331722339, "PASS"), (1343169713, "CHEAT"), (1344569016, "CHEAT")]

for rrid, tag in TARGETS:
    print("=" * 78)
    print(tag, rrid)
    print("=" * 78)
    d = cli.history.execute_request("POST", HOST + "/api/v70320/runnings/get_one_record",
                                    body_plain={"rrid": rrid}).get("data") or {}
    uuid = d.get("uuid")
    st = d.get("startTime")
    sport = d.get("sportType")
    print("  uuid=%s  startTime=%s  sportType=%s" % (uuid, st, sport))

    got = False
    for key in keys_for(uuid, st, UID, sport):
        r, err = signed(key, "Get")
        if err:
            print("    [sign失败] %-52s %s" % (key, err[:80]))
            continue
        data = r.get("data") or r
        url = None
        if isinstance(data, dict):
            url = data.get("signedUrl")
        elif isinstance(data, str):
            try:
                url = json.loads(data).get("signedUrl")
            except Exception:
                pass
        if not url:
            print("    [无URL]   %-52s resp=%s" % (key, json.dumps(r, ensure_ascii=False)[:120]))
            continue
        blob = dl(url)
        if blob is None:
            print("    [下载失败] %-52s" % key)
            continue
        print("    [命中] %s  -> %d 字节" % (key, len(blob)))
        out = os.path.join(BASE, "obs_%s_%s.json" % (tag, rrid))
        with open(out, "wb") as f:
            f.write(blob)
        print("    已保存:", out)
        got = True
        break
    if not got:
        print("    ⚠ 所有候选 key 都取不到")
    print()
