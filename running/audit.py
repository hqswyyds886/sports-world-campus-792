# -*- coding: utf-8 -*-
"""跨记录体检 —— 把历史记录算成一份可读报告，回答「这批记录看起来像真人吗」。

## 为什么需要这一层

单条记录的报文形态对齐之后（`pass_form.py` 那一层），还有一类问题只在
**多条记录之间**才暴露：

* 每天都在同一分钟起跑 —— 真人不会
* 每条都恰好 2000 米 —— 真人会有一天 2km、一天 3km
* 每条配速都一样 —— 同上
* 五条轨迹是同一个闭环 —— 学校操场就那么几条路线，但不会一模一样

服务端复核看的正是这些。本模块把它们变成提交前的可读指标，命中只提示、
不拦截 —— 阈值是「如果我是审核的人会先看哪几条」的经验值，不是协议规则。

## 与提交链路的关系

纯离线计算，不联网、不读账号。数据来源是历史记录列表（`cli.py --history`）
或本地导出的 `RunRecord` 列表。

## 各检查项含义

| 检查码 | 含义 | 命中意味着 |
|---|---|---|
| `AUDIT_STREAK` | 连续天数 | 一连 5 天以上，能画出一条直线 |
| `AUDIT_HOUR` | 起跑时刻集中度 | 六成以上落在同一整点 |
| `AUDIT_DIST_FLAT` | 里程变异系数 | < 0.05，每公里数都一样 |
| `AUDIT_PACE_FLAT` | 配速变异系数 | < 0.02，每条配速都一样 |
| `AUDIT_OVERLAP` | 两两轨迹重合度 | ≥ 0.90，同一条线 |
| `AUDIT_REVERSE` | 反向重合 | 同一条线反着跑（真人也会，提示即可）|
| `AUDIT_MIDNIGHT` | 近零点提交 | 触发时段规则风险 |
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .consistency import distance

# ---------------------------------------------------------------- 阈值
#: 连续天数到多少算「值得看一眼」。学校层面一般按周看，5 天已经能画出一根直线。
STREAK_WARN_DAYS = 5
#: 起跑时刻落在同一个整点的占比。真人有作息，但不会一周里八成都同一分钟。
HOUR_SHARE_WARN = 0.60
#: 里程变异系数低于这个值，说明每条都一样长。
DIST_CV_WARN = 0.05
#: 配速变异系数低于这个值，同上。
PACE_CV_WARN = 0.02
#: 两条轨迹重合到这个程度，就是同一条线。
OVERLAP_WARN = 0.90
#: 反向判定的容差（米）：首/中/尾三点互换后都在这个距离内，算「反着跑」。
REVERSE_TOL_M = 30.0
#: 离零点多少小时内算「近零点」。规则时段是 06:00–22:00，贴着边界提交最容易
#: 被判成「不在有效时段内」。
MIDNIGHT_MARGIN_H = 1

#: 所有检查码。
AUDIT_CODES = (
    "AUDIT_STREAK",
    "AUDIT_HOUR",
    "AUDIT_DIST_FLAT",
    "AUDIT_PACE_FLAT",
    "AUDIT_OVERLAP",
    "AUDIT_REVERSE",
    "AUDIT_MIDNIGHT",
)

LEVEL_INFO = "info"
LEVEL_WARN = "warn"


@dataclass
class Finding:
    """一条体检结论。`code` 用 `AUDIT_*` 前缀，与 preflight 的 `PACE_*` 区分。"""
    code: str
    level: str
    text: str

    def line(self) -> str:
        return "[%s] %s: %s" % ("注意" if self.level == LEVEL_WARN else "陈述",
                                self.code, self.text)


@dataclass
class Record:
    """一条历史记录里体检需要的字段。

    只放最小集：时间、里程、时长、轨迹点（可选，没有就跳过重合度检查）。
    """
    rrid: int = 0
    start_ms: int = 0
    distance_m: float = 0.0
    time_sec: float = 0.0
    #: 轨迹点 `(lat, lng)` 序列，GCJ-02。空列表表示没有轨迹数据。
    track: List[Tuple[float, float]] = field(default_factory=list)

    @property
    def pace_min_per_km(self) -> float:
        """配速（分/公里）。"""
        if self.distance_m <= 0 or self.time_sec <= 0:
            return 0.0
        return (self.time_sec / 60.0) / (self.distance_m / 1000.0)


@dataclass
class Metrics:
    """算出来的全部指标，不含判断。"""
    count: int = 0
    span_days: int = 0
    streak_best: int = 0
    streak_cur: int = 0
    hour: int = 0
    hour_share: float = 0.0
    dist_mean: float = 0.0
    dist_cv: float = 0.0
    pace_mean: float = 0.0
    pace_cv: float = 0.0
    near_midnight: int = 0
    #: 重合度最高的一对 `(i, j, 重合度)`，0 基
    overlap: Optional[Tuple[int, int, float]] = None
    #: 反向重合的一对
    reversed_pair: Optional[Tuple[int, int, float]] = None
    #: 全部两两结果，按重合度降序 `(i, j, 重合度, 是否反向)`
    pairs: List[Tuple[int, int, float, bool]] = field(default_factory=list)


def _cv(values: Sequence[float]) -> float:
    """变异系数 = 标准差 / 均值。样本不足或均值为 0 时返回 0。"""
    nums = [float(v) for v in values if v is not None and float(v) > 0]
    if len(nums) < 2:
        return 0.0
    mean = sum(nums) / len(nums)
    if mean <= 0:
        return 0.0
    var = sum((v - mean) ** 2 for v in nums) / len(nums)
    return math.sqrt(var) / mean


def _beijing_hour(ms: int) -> int:
    """毫秒戳 → 北京时间的整点。"""
    dt = (datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc)
          + datetime.timedelta(hours=8))
    return dt.hour


def _beijing_date(ms: int) -> datetime.date:
    return (datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc)
            + datetime.timedelta(hours=8)).date()


def _overlap(ta: Sequence[Tuple[float, float]],
             tb: Sequence[Tuple[float, float]],
             radius_m: float = 15.0) -> float:
    """两条轨迹的重合度：a 的点里有多少比例能在 b 上找到 `radius_m` 内的点。

    对称取平均（a→b 与 b→a），因为两条轨迹采样密度可能不同。
    """
    if not ta or not tb:
        return 0.0

    def one_way(src, dst):
        hit = 0
        for p in src:
            if any(distance(p, q) <= radius_m for q in dst):
                hit += 1
        return hit / len(src)

    return (one_way(ta, tb) + one_way(tb, ta)) / 2.0


def _is_reversed(ta: Sequence[Tuple[float, float]],
                 tb: Sequence[Tuple[float, float]]) -> bool:
    """两条轨迹是否「同一条线反着跑」。

    **不能只比首尾**：记分跑绕的是闭合跑道，首点≈末点，于是任意两条同跑道
    记录（同向也好反向也好）首尾距离都接近 0，「反向」恒为真。
    取样的索引也要避开中心对称位：`i` 与 `n-1-i` 在 `i=(n-1)/2` 时是同一个点。
    用 `n/6, n/3, n/2` 三处，两两间隔够远，同向时必然落在轨迹不同位置。
    """
    n = min(len(ta), len(tb))
    if n < 4:
        return False
    return all(distance(ta[i], tb[n - 1 - i]) <= REVERSE_TOL_M
               for i in (n // 6, n // 3, n // 2))


def compute_metrics(records: Sequence[Record]) -> Metrics:
    """算指标。纯函数，不读环境、不联网。"""
    m = Metrics()
    rows = [r for r in records if r.start_ms > 0]
    m.count = len(rows)
    if not rows:
        return m

    rows.sort(key=lambda r: r.start_ms)

    # 跨度与连续天数
    days = sorted({_beijing_date(r.start_ms) for r in rows})
    m.span_days = (days[-1] - days[0]).days + 1 if days else 0
    best = cur = 1
    for prev, nxt in zip(days, days[1:]):
        if (nxt - prev).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    m.streak_best = best
    m.streak_cur = cur

    # 起跑整点集中度
    hours = [_beijing_hour(r.start_ms) for r in rows]
    counts: Dict[int, int] = {}
    for h in hours:
        counts[h] = counts.get(h, 0) + 1
    m.hour, top = max(counts.items(), key=lambda kv: kv[1])
    m.hour_share = top / len(hours)

    # 里程与配速的变异系数
    m.dist_mean = sum(r.distance_m for r in rows) / len(rows)
    m.dist_cv = _cv([r.distance_m for r in rows])
    paces = [r.pace_min_per_km for r in rows]
    m.pace_mean = sum(paces) / len(paces)
    m.pace_cv = _cv(paces)

    # 近零点提交
    m.near_midnight = sum(1 for h in hours
                          if h < MIDNIGHT_MARGIN_H or h >= 24 - MIDNIGHT_MARGIN_H)

    # 两两重合
    idx = [i for i, r in enumerate(rows) if len(r.track) >= 2]
    pairs: List[Tuple[int, int, float, bool]] = []
    for x in range(len(idx)):
        for y in range(x + 1, len(idx)):
            i, j = idx[x], idx[y]
            ov = _overlap(rows[i].track, rows[j].track)
            pairs.append((i, j, ov, _is_reversed(rows[i].track, rows[j].track)))
    pairs.sort(key=lambda p: -p[2])
    m.pairs = pairs
    if pairs:
        m.overlap = (pairs[0][0], pairs[0][1], pairs[0][2])
        rev = [p for p in pairs if p[3] and p[2] >= OVERLAP_WARN]
        if rev:
            m.reversed_pair = (rev[0][0], rev[0][1], rev[0][2])
    return m


def findings_of(m: Metrics) -> List[Finding]:
    """把指标转成结论。命中只提示，不拦提交。"""
    out: List[Finding] = []
    if m.count == 0:
        return out

    if m.streak_best >= STREAK_WARN_DAYS:
        out.append(Finding("AUDIT_STREAK", LEVEL_WARN,
                           "最长连续 %d 天有记录（跨度 %d 天），能画出一条直线；"
                           "建议隔天或插入休息日" % (m.streak_best, m.span_days)))
    else:
        out.append(Finding("AUDIT_STREAK", LEVEL_INFO,
                           "最长连续 %d 天，跨度 %d 天" % (m.streak_best, m.span_days)))

    if m.hour_share >= HOUR_SHARE_WARN:
        out.append(Finding("AUDIT_HOUR", LEVEL_WARN,
                           "%.0f%% 的记录起跑于 %02d 点（真人不会这么准）；"
                           "建议把起跑时刻打散到不同整点"
                           % (m.hour_share * 100, m.hour)))
    else:
        out.append(Finding("AUDIT_HOUR", LEVEL_INFO,
                           "起跑时刻最集中在 %02d 点，占 %.0f%%"
                           % (m.hour, m.hour_share * 100)))

    if m.dist_cv < DIST_CV_WARN:
        out.append(Finding("AUDIT_DIST_FLAT", LEVEL_WARN,
                           "里程变异系数 %.4f（< %.2f），每条都差不多长；"
                           "真人会有一天 2km、一天 3km" % (m.dist_cv, DIST_CV_WARN)))
    else:
        out.append(Finding("AUDIT_DIST_FLAT", LEVEL_INFO,
                           "里程变异系数 %.4f，均值 %.0fm" % (m.dist_cv, m.dist_mean)))

    if m.pace_cv < PACE_CV_WARN:
        out.append(Finding("AUDIT_PACE_FLAT", LEVEL_WARN,
                           "配速变异系数 %.4f（< %.2f），每条配速都一样；"
                           "建议让配速在 %.1f~%.1f 分/km 之间浮动"
                           % (m.pace_cv, PACE_CV_WARN,
                              m.pace_mean * 0.92, m.pace_mean * 1.08)))
    else:
        out.append(Finding("AUDIT_PACE_FLAT", LEVEL_INFO,
                           "配速变异系数 %.4f，均值 %.2f 分/km"
                           % (m.pace_cv, m.pace_mean)))

    if m.overlap and m.overlap[2] >= OVERLAP_WARN:
        out.append(Finding("AUDIT_OVERLAP", LEVEL_WARN,
                           "记录 %d 与 %d 的轨迹重合度 %.0f%%（≥ %.0f%%），"
                           "是同一条线；建议换路线或改起跑位置"
                           % (m.overlap[0], m.overlap[1], m.overlap[2] * 100,
                              OVERLAP_WARN * 100)))
    elif m.overlap:
        out.append(Finding("AUDIT_OVERLAP", LEVEL_INFO,
                           "最高重合度 %.0f%%（记录 %d 与 %d）"
                           % (m.overlap[2] * 100, m.overlap[0], m.overlap[1])))
    else:
        out.append(Finding("AUDIT_OVERLAP", LEVEL_INFO, "没有轨迹数据，跳过重合度检查"))

    if m.reversed_pair:
        out.append(Finding("AUDIT_REVERSE", LEVEL_INFO,
                           "记录 %d 与 %d 是同一条线反向跑（重合度 %.0f%%）；"
                           "反向跑是真人行为，不算问题"
                           % (m.reversed_pair[0], m.reversed_pair[1],
                              m.reversed_pair[2] * 100)))

    if m.near_midnight > 0:
        out.append(Finding("AUDIT_MIDNIGHT", LEVEL_WARN,
                           "%d 条记录在零点前后 %d 小时内起跑；"
                           "规则时段常见 06:00–22:00，贴边界容易被判不在时段内"
                           % (m.near_midnight, MIDNIGHT_MARGIN_H)))
    return out


def report(records: Sequence[Record]) -> Tuple[Metrics, List[Finding]]:
    """一次性算出指标与结论。"""
    m = compute_metrics(records)
    return m, findings_of(m)


def suggest(m: Metrics, findings: Sequence[Finding]) -> List[str]:
    """基于结论给出可执行的动作建议。"""
    codes = {f.code for f in findings if f.level == LEVEL_WARN}
    tips: List[str] = []
    if "AUDIT_STREAK" in codes:
        tips.append("下次提交隔一天，或插入一天不跑")
    if "AUDIT_HOUR" in codes:
        tips.append("起跑时刻换到另一个整点（例如 %02d 点改到 %02d 点）"
                    % (m.hour, (m.hour + 3) % 24))
    if "AUDIT_DIST_FLAT" in codes:
        tips.append("里程改成 %.0f~%.0f 米之间浮动，不要每条都同一数字"
                    % (max(2000, m.dist_mean * 0.85), m.dist_mean * 1.15))
    if "AUDIT_PACE_FLAT" in codes:
        tips.append("配速改到 %.2f~%.2f 分/公里，别每条都一样"
                    % (m.pace_mean * 0.92, m.pace_mean * 1.08))
    if "AUDIT_OVERLAP" in codes:
        tips.append("换一条路线，或把起跑点挪开几十米")
    if "AUDIT_MIDNIGHT" in codes:
        tips.append("把提交时间挪到 08:00–20:00 之间")
    if not tips:
        tips.append("当前指标没有明显模式，可以正常提交")
    return tips


def from_history_rows(rows: Sequence[Dict[str, Any]],
                      tracks: Optional[Dict[int, List[Tuple[float, float]]]] = None
                      ) -> List[Record]:
    """把 `--history` 那种列表响应转成 `Record` 列表。

    `tracks` 可选：`rrid -> 轨迹点`。没有轨迹时重合度检查会跳过。
    """
    out: List[Record] = []
    for row in rows or []:
        rrid = int(row.get("rrid") or 0)
        out.append(Record(
            rrid=rrid,
            start_ms=int(row.get("startTime") or 0),
            distance_m=float(row.get("totalDis") or 0.0),
            time_sec=float(row.get("totalTime") or 0.0),
            track=list((tracks or {}).get(rrid) or []),
        ))
    return out
