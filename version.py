# -*- coding: utf-8 -*-
"""版本元数据。

**改版本号时三处一起改**，否则 `--version` 与 CHANGELOG 会对不上：

    1. 本文件 __version__
    2. CHANGELOG.md  新增条目（Keep a Changelog 格式）
    3. VERSION.md    兼容性矩阵

版本号规则见 CHANGELOG.md 末尾：主版本号只在报文协议层不兼容变更时递增，
修复类递增次版本，纯文档/工具递增修订号。
"""

__version__ = "1.0.0"
__released__ = "2026-11-24"

#: 本实现对应的官方 App 版本。服务端按 `appVersion` 头做兼容判断，
#: 也是加密栈与字段语义的基准。
TARGET_APP_VERSION = "7.3.92"

#: 协议加密栈名称与版本（易盾 NetSecKit）。
PROTOCOL = "NetSecKit 4.2.4"

#: 一个简短的运行期信息串，便于日志里定位版本。
VERSION_TAG = "sports-world-campus/{v} (app {a}, {p})".format(
    v=__version__, a=TARGET_APP_VERSION, p=PROTOCOL)


def info() -> dict:
    """结构化版本信息，供脚本与 `--version` 使用。"""
    return {
        "version": __version__,
        "released": __released__,
        "target_app": TARGET_APP_VERSION,
        "protocol": PROTOCOL,
        "tag": VERSION_TAG,
    }
