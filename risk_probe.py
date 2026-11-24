# -*- coding: utf-8 -*-
"""账号风控面全量体检：控制信令 / 作弊库 / 无障碍策略 / 信用分 / 学期进度。"""
import os, sys, json

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")

from sport_client import SportClient792
from core.session import load_session
from config_loader import get_session_file_path

sess = load_session(get_session_file_path())
if not sess:
    print("无缓存凭据，先登录"); sys.exit(1)

cli = SportClient792(uid=sess.get("uid"), token=sess.get("token"), unid=sess.get("unid"))
tel = cli.telemetry
# 埋点通道与主网关共用同一套请求器
netsec = cli.profile  # ProfileClient 继承 BaseNetSecClient，本身就是请求器
print("netsec 对象:", type(netsec).__name__ if netsec else "未找到")
print()

def show(title, fn):
    print("=" * 72); print(title); print("=" * 72)
    try:
        r = fn()
        print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])
    except Exception as e:
        print("失败:", type(e).__name__, e)
    print()

show("1. 控制信令（封禁/冻结/维护）", tel.check_control_message)
if netsec is not None:
    show("2. 信用分弹窗", lambda: tel.get_credit_popup(netsec))
    show("3. 作弊工具特征库", lambda: tel.get_cheat_blacklist(netsec))
    show("4. 无障碍反辅助策略", lambda: tel.get_barrier_free_policy(netsec))
