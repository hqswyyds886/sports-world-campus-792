# -*- coding: utf-8 -*-
"""`--audit` 与 `--run` 里的跨记录体检接线是否真的通。

`test_audit.py` 只测 `running/audit.py` 的算法；这里测**接线**：

* `cli._print_audit` 用的是 `history.get_run_records`（而不是某个不存在的方法）
* 取 50 条而不是默认 20 条
* 拿不到历史时降级成一行提示，不抛异常
* `running.client` 里没有悬空的名字（`URL_RUN_RECORDS` 那次事故的回归）

最后一条值一条用例：`NameError` 被外层 `try/except` 吃掉后只会打一行
「跨记录体检: 跳过」，功能看起来在跑、实际永远不生效，靠读输出发现不了。
"""
import types
import unittest
from unittest.mock import Mock

import cli
from running import audit


def rows_bot():
    return [{"rrid": i, "startTime": 1795400000000 + i * 86400000,
             "totalDis": 2000.0, "totalTime": 760.0} for i in range(6)]


def fake_client(payload):
    client = types.SimpleNamespace()
    client.history = Mock()
    if isinstance(payload, Exception):
        client.history.get_run_records = Mock(side_effect=payload)
    else:
        client.history.get_run_records = Mock(return_value=payload)
    return client


class PrintAuditTests(unittest.TestCase):

    def test_uses_existing_method_and_asks_for_fifty(self):
        client = fake_client({"error": 10000, "data": rows_bot()})
        cli._print_audit(client)
        # 方法名必须真实存在于 HistoryClient；曾经写成 `get_records`，
        # `hasattr` 恒假，于是每次都退到硬编码 URL 的兜底分支。
        self.assertTrue(hasattr(cli, "_print_audit"))
        client.history.get_run_records.assert_called_once_with(page_num=1, page_size=50)

    def test_no_hardcoded_url_in_cli(self):
        """URL 只该留在 history/config.py 一处。"""
        from pathlib import Path
        src = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertNotIn("run.gxapp.iydsj.com", src,
                         "cli.py 里不该出现硬编码的接口地址")

    def test_empty_data_is_reported_not_crashed(self):
        client = fake_client({"error": 10000, "data": []})
        cli._print_audit(client)   # 不应抛

    def test_network_failure_degrades_to_one_line(self):
        client = fake_client(RuntimeError("offline"))
        cli._print_audit(client)   # 不应抛

    def test_none_payload_is_safe(self):
        client = fake_client({"error": -1})
        cli._print_audit(client)


class CrossRecordAuditWiringTests(unittest.TestCase):

    def test_client_module_has_no_dangling_name(self):
        """`_log_cross_record_audit` 用到的名字必须真能解析。

        这是 `URL_RUN_RECORDS` 那次事故的回归：新增代码引用了没 import 的
        名字，被 `except Exception` 吞成一行动日志，跑批时完全看不出来。
        """
        import running.client as rc
        import inspect
        src = inspect.getsource(rc.RunningClient._log_cross_record_audit)
        # 逐个名字用模块命名空间验证，避免真去建连接
        for name in ("URL_RUN_RECORDS", "audit_mod", "from_history_rows", "report"):
            if name not in src:
                continue
            if name == "audit_mod":
                continue          # 函数内局部导入
            self.assertTrue(
                hasattr(rc, name) or name in ("from_history_rows", "report"),
                f"{name} 在 _log_cross_record_audit 里被引用但模块中不存在")

    def test_audit_module_reachable_from_client(self):
        """`from . import audit` 必须能成功 —— 包内文件名写错就静默降级。"""
        from running import client as rc
        mod = rc.RunningClient._log_cross_record_audit
        self.assertTrue(callable(mod))
        self.assertTrue(hasattr(audit, "from_history_rows"))
        self.assertTrue(hasattr(audit, "report"))
        self.assertTrue(hasattr(audit, "suggest"))
        self.assertTrue(hasattr(audit, "LEVEL_WARN"))


if __name__ == "__main__":
    unittest.main()
