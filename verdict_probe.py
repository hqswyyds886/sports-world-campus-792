# -*- coding: utf-8 -*-
"""拉取每条历史记录的完整详情，找出服务端真正的判罚理由字段。"""
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

RR = [1356929149, 1356874884, 1356829957, 1344569016, 1343169713]

# 先看列表原始结构里有哪些字段
raw = cli.history.execute_request("POST", "https://run.gxapp.iydsj.com/api/v70230/runnings/records",
                                  body_plain={"pageNum": 1, "pageSize": 10})
print("=== 列表原始响应（截断 4000）===")
print(json.dumps(raw, ensure_ascii=False, indent=2)[:4000])
print()

for rrid in RR:
    print("=" * 78)
    print("rrid =", rrid)
    print("=" * 78)
    try:
        d = cli.history.execute_request(
            "POST", "https://run.gxapp.iydsj.com/api/v70320/runnings/get_one_record",
            body_plain={"rrid": rrid})
        s = json.dumps(d, ensure_ascii=False, indent=2)
        # 只打关键字段，避免轨迹刷屏
        print(s[:2500])
    except Exception as e:
        print("失败:", type(e).__name__, e)
    print()
