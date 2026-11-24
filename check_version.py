# -*- coding: utf-8 -*-
"""版本一致性检查 —— 确保版本号三处不漂移。

改版本号时最容易出的错：只改了 `version.py`，忘了 CHANGELOG 加条目，
或者 VERSION.md 的兼容性矩阵没跟上。本脚本把这三处对齐关系变成断言。

用法::

    python check_version.py           # 检查
    python check_version.py --bump minor "改动说明"   # 递增次版本并同步三处
"""
from __future__ import annotations

import argparse
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def read(path: str) -> str:
    with open(os.path.join(BASE, path), encoding="utf-8") as fp:
        return fp.read()


def py_version() -> dict:
    import version
    return version.info()


def changelog_versions(text: str) -> list:
    """从 CHANGELOG 里抓所有已发布的版本号（不含 Unreleased）。"""
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M)


def changelog_has_version(text: str, ver: str) -> bool:
    return bool(re.search(r"^## \[%s\]" % re.escape(ver), text, re.M))


def version_md_current(text: str) -> str:
    m = re.search(r'current\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else ""


def version_md_target(text: str) -> str:
    m = re.search(r'target_app\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="版本一致性检查")
    ap.add_argument("--bump", choices=["major", "minor", "patch"],
                    help="递增哪个号段")
    ap.add_argument("--note", default="", help="本次改动的简述（写进 CHANGELOG）")
    args = ap.parse_args()

    meta = py_version()
    cur = meta["version"]
    cl_text = read("CHANGELOG.md")
    vm_text = read("VERSION.md")

    if args.bump:
        major, minor, patch = (int(x) for x in cur.split("."))
        if args.bump == "major":
            major, minor, patch = major + 1, 0, 0
        elif args.bump == "minor":
            minor, patch = minor + 1, 0
        else:
            patch += 1
        new = "%d.%d.%d" % (major, minor, patch)
        note = args.note or "（待补充）"

        # 1. version.py
        p = os.path.join(BASE, "version.py")
        text = read("version.py")
        text = re.sub(r'__version__ = "[^"]+"', '__version__ = "%s"' % new, text)
        import datetime
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        text = re.sub(r'__released__ = "[^"]+"', '__released__ = "%s"' % today, text)
        open(p, "w", encoding="utf-8", newline="\n").write(text)

        # 2. CHANGELOG.md — 在 Unreleased 段之后插入新版本段
        marker = "## [Unreleased]"
        idx = cl_text.find(marker)
        if idx < 0:
            print("CHANGELOG.md 里找不到 [Unreleased] 段，手工处理")
            return 1
        # 找到 Unreleased 段结束位置（下一个 "---" 之前）
        seg_end = cl_text.find("\n---\n", idx)
        if seg_end < 0:
            seg_end = idx + len(marker)
        else:
            seg_end += len("\n---\n")
        new_section = (
            "\n## [%s] - %s\n\n### 变更\n\n- %s\n\n---\n" % (new, today, note)
        )
        cl_text = cl_text[:seg_end] + new_section + cl_text[seg_end:]
        open(os.path.join(BASE, "CHANGELOG.md"), "w",
             encoding="utf-8", newline="\n").write(cl_text)

        # 3. VERSION.md
        vm_text = re.sub(r'current\s*=\s*"[^"]+"', 'current     = "%s"' % new, vm_text)
        vm_text = re.sub(r'released\s*=\s*"[^"]+"', 'released    = "%s"' % today, vm_text)
        open(os.path.join(BASE, "VERSION.md"), "w",
             encoding="utf-8", newline="\n").write(vm_text)

        print("已从 %s 递增到 %s（%s），三处已同步" % (cur, new, today))
        print("  1. version.py     __version__ / __released__")
        print("  2. CHANGELOG.md   新增 [%s] 段" % new)
        print("  3. VERSION.md     current / released")
        print()
        print("别忘了补 CHANGELOG 里的具体条目，以及 README 的版本徽章。")
        return 0

    # ---------------- 检查模式
    bad = 0

    def check(name, ok, expect, got):
        nonlocal bad
        if not ok:
            bad += 1
        print("  [%s] %-30s 期望 %-14s 实际 %s" % (
            "OK " if ok else "BAD", name, str(expect), str(got)))

    print("=" * 70)
    print("版本一致性检查")
    print("=" * 70)

    check("version.py 版本号格式", bool(re.fullmatch(r"\d+\.\d+\.\d+", cur)),
          "X.Y.Z", cur)
    check("CHANGELOG 有该版本段", changelog_has_version(cl_text, cur), cur,
          "有" if changelog_has_version(cl_text, cur) else "无")
    check("VERSION.md current 一致", version_md_current(vm_text) == cur,
          cur, version_md_current(vm_text))
    check("VERSION.md target_app 一致",
          version_md_target(vm_text) == meta["target_app"],
          meta["target_app"], version_md_target(vm_text))

    # README 徽章
    rm_text = read("README.md")
    m = re.search(r"badge/version-([0-9.]+)-", rm_text)
    badge = m.group(1) if m else ""
    check("README 版本徽章一致", badge == cur, cur, badge or "未找到")

    # CHANGELOG 版本按语义化倒序
    vers = changelog_versions(cl_text)
    def key(v):
        return tuple(int(x) for x in v.split("."))
    ordered = vers == sorted(vers, key=key, reverse=True)
    check("CHANGELOG 版本倒序排列", ordered, "从新到旧", vers[:4])

    print()
    print("=" * 70)
    if bad == 0:
        print("结论：四处版本号一致")
    else:
        print("结论：%d 处不一致，用 --bump 或手工对齐" % bad)
    print("=" * 70)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
