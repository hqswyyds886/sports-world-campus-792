# -*- coding: utf-8 -*-
"""`running/audit.py` 的离线回归：跨记录体检。

这一层的输出只用来提示，不拦截提交，所以测试重点是**指标算法本身对不对**，
而不是「有没有拦住」。三类场景：

* 机器人式样本必须全部命中 `AUDIT_*` 警告；
* 真人式样本必须基本不命中（尤其不能把「反向跑」当问题报）；
* 无轨迹 / 单条 / 空列表这类退化输入必须不抛异常、如实降级。

时间戳统一按北京时间构造再转毫秒 —— 体检按北京时间的日期与整点分桶，
用本地时区构造会在非 UTC+8 的机器上算错，而 CI 机器不一定是 UTC+8。
"""
import datetime
import math
import unittest

from running import audit


def bj_ms(day: int, hour: int, minute: int = 0) -> int:
    """2026-11-`day` `hour`:`minute` 北京时间 → 毫秒戳。"""
    dt = datetime.datetime(2026, 11, day, hour, minute,
                           tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    return int(dt.timestamp() * 1000)


def row(rrid: int, day: int, hour: int, dist: float, sec: float, minute: int = 0):
    return {"rrid": rrid, "startTime": bj_ms(day, hour, minute),
            "totalDis": float(dist), "totalTime": float(sec)}


def ring(n: int = 60, radius_m: float = 60.0,
         cx: float = 113.38, cy: float = 23.34):
    """绕 (cx, cy) 的闭合圆环，GCJ-02 近似等距。"""
    k = 111320.0
    return [(cy + radius_m * math.sin(2 * math.pi * i / n) / k,
             cx + radius_m * math.cos(2 * math.pi * i / n) / (k * math.cos(math.radians(cy))))
            for i in range(n)]


class RobotPatternTests(unittest.TestCase):
    """典型「刷」出来的序列：连续、同整点、同里程、同配速。"""

    def setUp(self):
        rows = [row(i, 10 + i, 10, 2000, 760) for i in range(6)]
        self.metrics, self.findings = audit.report(audit.from_history_rows(rows))
        self.codes = {f.code for f in self.findings if f.level == audit.LEVEL_WARN}

    def test_streak_detected(self):
        self.assertEqual(self.metrics.streak_best, 6)
        self.assertIn("AUDIT_STREAK", self.codes)

    def test_hour_concentration_detected(self):
        self.assertEqual(self.metrics.hour, 10)
        self.assertAlmostEqual(self.metrics.hour_share, 1.0)
        self.assertIn("AUDIT_HOUR", self.codes)

    def test_flat_distance_and_pace_detected(self):
        self.assertAlmostEqual(self.metrics.dist_cv, 0.0, places=6)
        self.assertAlmostEqual(self.metrics.pace_cv, 0.0, places=6)
        self.assertIn("AUDIT_DIST_FLAT", self.codes)
        self.assertIn("AUDIT_PACE_FLAT", self.codes)

    def test_suggestions_are_actionable(self):
        tips = audit.suggest(self.metrics, self.findings)
        self.assertTrue(tips)
        self.assertTrue(any("隔一天" in t for t in tips))
        self.assertTrue(any("整点" in t for t in tips))


class HumanPatternTests(unittest.TestCase):
    """隔天、不同整点、里程有起伏 —— 不该被判成同一种模式。"""

    def setUp(self):
        data = [(0, 8, 2100, 780), (1, 17, 2500, 910), (3, 7, 1900, 700),
                (4, 18, 3000, 1080), (6, 9, 2200, 800)]
        rows = [row(i, 10 + d, h, dis, t) for i, (d, h, dis, t) in enumerate(data)]
        self.metrics, self.findings = audit.report(audit.from_history_rows(rows))
        self.codes = {f.code for f in self.findings if f.level == audit.LEVEL_WARN}

    def test_streak_not_flagged(self):
        self.assertEqual(self.metrics.streak_best, 2)
        self.assertNotIn("AUDIT_STREAK", self.codes)

    def test_hour_not_flagged(self):
        self.assertAlmostEqual(self.metrics.hour_share, 0.2)
        self.assertNotIn("AUDIT_HOUR", self.codes)

    def test_distance_not_flagged(self):
        self.assertGreater(self.metrics.dist_cv, audit.DIST_CV_WARN)
        self.assertNotIn("AUDIT_DIST_FLAT", self.codes)

    def test_no_warning_still_gives_advice(self):
        """没有命中也要给出可读输出，不能是空列表。"""
        self.assertTrue(audit.suggest(self.metrics, self.findings))


class TrackOverlapTests(unittest.TestCase):

    def test_identical_tracks_flagged(self):
        a, b = ring(), ring()
        rows = [row(0, 10, 10, 2000, 700), row(1, 11, 10, 2000, 700)]
        metrics, findings = audit.report(
            audit.from_history_rows(rows, {0: a, 1: b}))
        self.assertAlmostEqual(metrics.overlap[2], 1.0, places=3)
        self.assertIn("AUDIT_OVERLAP",
                      {f.code for f in findings if f.level == audit.LEVEL_WARN})

    def test_different_tracks_not_flagged(self):
        rows = [row(0, 10, 10, 2000, 700), row(1, 11, 10, 2000, 700)]
        metrics, findings = audit.report(audit.from_history_rows(
            rows, {0: ring(), 1: ring(cx=113.40, cy=23.36)}))
        self.assertLess(metrics.overlap[2], audit.OVERLAP_WARN)
        self.assertNotIn("AUDIT_OVERLAP",
                         {f.code for f in findings if f.level == audit.LEVEL_WARN})

    def test_reversed_is_info_not_warning(self):
        """反向跑是真人行为，只陈述、不告警。"""
        rows = [row(0, 10, 10, 2000, 700), row(1, 11, 10, 2000, 700)]
        metrics, findings = audit.report(audit.from_history_rows(
            rows, {0: ring(), 1: list(reversed(ring()))}))
        self.assertIsNotNone(metrics.reversed_pair)
        levels = {f.code: f.level for f in findings}
        self.assertEqual(levels.get("AUDIT_REVERSE"), audit.LEVEL_INFO)

    def test_shifted_start_is_not_reversed(self):
        """起跑点错开几十米的同向环，不能误判成反向。"""
        base = ring()
        shift = 15
        shifted = base[shift:] + base[:shift]
        self.assertFalse(audit._is_reversed(base, shifted))

    def test_missing_track_degrades(self):
        rows = [row(0, 10, 10, 2000, 700), row(1, 11, 10, 2000, 700)]
        metrics, findings = audit.report(audit.from_history_rows(rows))
        self.assertIsNone(metrics.overlap)
        self.assertIn("没有轨迹数据",
                      next(f.text for f in findings if f.code == "AUDIT_OVERLAP"))


class DegenerateInputTests(unittest.TestCase):

    def test_empty(self):
        metrics, findings = audit.report([])
        self.assertEqual(metrics.count, 0)
        self.assertEqual(findings, [])
        self.assertTrue(audit.suggest(metrics, findings))

    def test_single_record(self):
        metrics, findings = audit.report(audit.from_history_rows([row(0, 10, 10, 2000, 700)]))
        self.assertEqual(metrics.count, 1)
        self.assertEqual(metrics.streak_best, 1)
        # 单条样本算不出变异系数，只能是 0，但不应崩
        self.assertAlmostEqual(metrics.dist_cv, 0.0)
        self.assertTrue(findings)

    def test_zero_start_time_is_skipped(self):
        """服务端偶发返回 startTime=0 的占位行，不能让它污染日期分桶。"""
        rows = [row(0, 10, 10, 2000, 700), {"rrid": 9, "startTime": 0,
                                            "totalDis": 0.0, "totalTime": 0.0}]
        metrics, _ = audit.report(audit.from_history_rows(rows))
        self.assertEqual(metrics.count, 1)

    def test_midnight_flagged(self):
        # 边界是「零点前后一小时」开区间：23 点在内，01 点已是边界外。
        rows = [row(0, 10, 0, 2000, 700), row(1, 11, 23, 2100, 720)]
        metrics, findings = audit.report(audit.from_history_rows(rows))
        self.assertEqual(metrics.near_midnight, 2)
        self.assertIn("AUDIT_MIDNIGHT",
                      {f.code for f in findings if f.level == audit.LEVEL_WARN})

    def test_one_am_is_outside_margin(self):
        rows = [row(0, 10, 1, 2000, 700)]
        metrics, _ = audit.report(audit.from_history_rows(rows))
        self.assertEqual(metrics.near_midnight, 0)


class FromHistoryRowsTests(unittest.TestCase):

    def test_maps_fields(self):
        [r] = audit.from_history_rows([row(7, 10, 10, 2008, 663)])
        self.assertEqual(r.rrid, 7)
        self.assertAlmostEqual(r.distance_m, 2008.0)
        self.assertAlmostEqual(r.time_sec, 663.0)
        self.assertEqual(r.track, [])

    def test_pace_uses_server_units(self):
        """服务端 totalTime 已经是秒，不能再按毫秒猜。"""
        [r] = audit.from_history_rows([row(1, 10, 10, 2000, 760)])
        self.assertAlmostEqual(r.pace_min_per_km, 760 / 60.0 / 2.0, places=6)

    def test_none_and_empty_safe(self):
        self.assertEqual(audit.from_history_rows([]), [])
        self.assertEqual(audit.from_history_rows(None), [])


if __name__ == "__main__":
    unittest.main()
