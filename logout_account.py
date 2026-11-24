# -*- coding: utf-8 -*-
"""退出运动世界校园账号 —— 真正让服务端 token 失效，再清本地凭据。

## 为什么不能只删 .session.json

只清本地状态的话，服务端那边的会话**仍然有效**，账号被标记为「已登录」。
这时候再登录会被判成「其他设备」，直接返回：

    10121 此账号已在其他设备登录，因账号保护机制，原状态未退出

然后被锁一小时。所以必须先调服务端注销接口，确认生效后再删本地文件。

接口：`POST /api/v6/user/logout`，token 走 header、body 是空对象 `{}`。
（本项目 README 里说「未实现服务端注销接口」，那是没找到，实际可用。）

## 判定标准

解析失败**不能**当成成功。服务端可能返回 HTML 错误页、空响应或被网关截断
的内容，把这些当成「登出成功」比不登出更糟 —— 下次重登直接撞 10121。
所以这里只有明确拿到 `error == 10000` 才算成功。
"""
from __future__ import annotations

import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")

from sport_client import SportClient792                      # noqa: E402
from core.session import load_session                        # noqa: E402
from config_loader import get_session_file_path              # noqa: E402

RUN_HOST = "https://run.gxapp.iydsj.com"
LOGOUT_PATH = "/api/v6/user/logout"
CODE_OK = 10000


def confirms_logout(raw: str) -> bool:
    """响应是否明确确认登出成功。解析失败一律返回 False。"""
    try:
        v = json.loads(raw)
    except Exception:
        return False
    if not isinstance(v, dict):
        return False
    # 明文形态
    err = v.get("error", v.get("code"))
    if isinstance(err, int):
        return err == CODE_OK
    # 信封形态：{"r": "<内层json>", ...}
    inner_raw = v.get("r")
    if isinstance(inner_raw, str):
        try:
            inner = json.loads(inner_raw)
        except Exception:
            return False
        if isinstance(inner, dict):
            e = inner.get("error", inner.get("code"))
            if isinstance(e, int):
                return e == CODE_OK
    return False


def main() -> int:
    path = get_session_file_path()
    sess = load_session(path)
    if not sess:
        print("没有缓存凭据，本来就没登录")
        return 0

    token = sess.get("token") or ""
    uid = sess.get("uid") or ""
    print("当前账号 uid=%s  token=%s…" % (uid, token[:8] if token else "<空>"))

    if not token:
        print("token 为空，无需通知服务端，直接清本地凭据")
        os.remove(path)
        print("已删除本地凭据:", path)
        return 0

    cli = SportClient792(uid=uid, token=token, unid=sess.get("unid"))
    print("调用服务端注销接口 %s …" % LOGOUT_PATH)
    try:
        raw = cli.profile.execute_request("POST", RUN_HOST + LOGOUT_PATH,
                                          body_plain={})
    except Exception as exc:
        print("  ✗ 请求失败: %s" % exc)
        print()
        print("服务端未确认登出，**不要**直接删本地凭据 —— 否则服务端会话仍有效，")
        print("下次登录会撞 10121 被锁一小时。可以稍后重试本脚本。")
        return 1

    raw_text = json.dumps(raw, ensure_ascii=False) if not isinstance(raw, str) else raw
    ok = confirms_logout(raw_text)
    print("  响应: %s" % raw_text[:200])
    if not ok:
        print()
        print("  ✗ 服务端未明确确认登出（响应无法解析成 error=%d）" % CODE_OK)
        print("    按 fail-closed 处理：不删本地凭据，避免下次登录撞 10121。")
        return 1

    print("  ✓ 服务端已确认 token 失效")

    os.remove(path)
    print("  ✓ 已删除本地凭据:", path)

    # 账本里也留着提交记录，一并清掉登录相关痕迹
    state_ledger = os.path.join(BASE, "state", "run_ledger.json")
    if os.path.exists(state_ledger):
        try:
            data = json.loads(open(state_ledger, encoding="utf-8").read())
            if isinstance(data, dict) and "devices" in data:
                data["devices"] = []
                open(state_ledger, "w", encoding="utf-8").write(
                    json.dumps(data, ensure_ascii=False, indent=2))
                print("  ✓ 已清空账本中的设备指纹:", state_ledger)
        except Exception as exc:
            print("  · 账本清理跳过（%s）" % exc)

    print()
    print("已退出。")
    print("说明：手机 App 端的登录态不受影响（那是独立会话）。")
    print("      如果手机端也要退，在 App 内「我的 → 设置 → 退出登录」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
