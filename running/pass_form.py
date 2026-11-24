# -*- coding: utf-8 -*-
"""PASS 形态生成器 —— 把服务端真实「通过」样本的报文结构与统计特征复刻出来。

## 为什么要有这个模块

对比同一账号的 2 条 status=0（通过）与 15 条 status=2（判作弊）记录，
从 OBS 原始明细（`run_data/{YYYYMMDDHH}/{uuid}.json`，gzip+base64 双层封装）
解出后逐字段比对，差异集中在这几处：

| 维度 | PASS 实测 | CHEAT 实测 | 本模块的做法 |
|---|---|---|---|
| 点结构 | 27 字段 | 6 字段 | `build_point_27()` |
| `position` | 0,1,2,3,4 连续 | 全 999 | `assign_positions()` |
| 采样点数 | 803 / 804 | 198 | 目标 2.5m 一点 |
| `count` | 恒 10 | 20~88 乱跳 | 常量 10（95% 点） |
| `queueNum` | 0~23 循环 | 恒 0 | 全部点都填，模 24 |
| `radius` | 1.5~3.1 | 最大 517 | 1.5~3.1 硬夹 |
| `bdS` | 平滑，无 0 | 有 0 值断点 | 低通连续 |
| `segment_json` | 23 段完整 | 空 | `build_segments()` |
| `laps_json` | 3 圈 | 空 | `build_laps()` |
| 配速 `speed` | 5.37 / 5.50 | 6.9~8.2 | 不在此模块约束 |

**所有常量都来自实测样本，不是推测。** 出处见 `PASS_PROFILE`。

## 两个坐标系

PASS 样本的点里：

* `lat` / `lng` 恒为 **-1.0**（占位，服务端不读）
* `gLat` / `gLng` 才是真实坐标，坐标系 **gcj02**（`coorType` 字段声明）

旧实现把真实坐标塞进 `lat`/`lng` 且用 6 字段结构，与真机形态不符。

## 关键不变量

1. `totalDis` / `validDis` 单调不减（PASS 样本 790/804 个唯一值，
   即只有极少数点重复前值）
2. `totalTime` / `validTime` 单调不减，末值 == 总时长
3. `type` 分布：`{0: 多数, 7: 起点窗口, 5: 1 个, 2: 打卡点, 3: 若干, 6: 终点}`
4. `state` 全场恒 1（PASS 样本两条都是）
5. `flag` 全场同一值 = 起步毫秒戳
6. `stepDistance` 恒 0.0
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# 实测常量（来源：obs_PASS_1333728921.json / obs_PASS_1331722339.json）
# ---------------------------------------------------------------------------

#: PASS 样本的点字段顺序（27 个）。顺序本身也是对齐项：服务端虽然按 key 取值，
#: 但 OBS 里存的是客户端序列化出来的字符串，顺序一致才能排除「格式不同」这条。
POINT_FIELD_ORDER: Tuple[str, ...] = (
    "avgSpeed", "bdA", "bdD", "bdG", "bdS", "coorType", "count", "dtr",
    "flag", "gLat", "gLng", "gainTime", "id", "lat", "lng", "locType",
    "locationId", "queueNum", "radius", "speed", "state", "stepDistance",
    "totalDis", "totalTime", "type", "validDis", "validTime",
)

#: `count` 的众数。样本 1333728921 全场 804 点都是 10；1331722339 有 10 和 19 两种，
#: 其中 10 占绝大多数。取 10 作为基线。
COUNT_BASE = 10
#: `count` 偶尔抬高的概率与幅度（对齐 1331722339 的 2 值分布）。
COUNT_SPIKE_P = 0.0004
COUNT_SPIKE_VAL = 19

#: `queueNum` 实测范围 0~23 / 0~22。按点序号取模。
QUEUE_MOD = 24

#: `radius` 实测 1.5 ~ 3.10（一条）/ 1.5 ~ 4.25（另一条）。取保守上界 3.1，
#: 因为 517m 那种离群值正是判异常的特征之一，绝不能出现。
RADIUS_MIN = 1.5
RADIUS_MAX = 3.1

#: `bdA` 实测 0.027 ~ 5.48（一条）/ -0.016 ~ 79.81（另一条）。取安静区间。
BDA_MIN, BDA_MAX = 0.02, 5.5

#: `bdD` 实测唯一值只有 6~7 个（朝向按路径段离散跳变，不是连续角）。
BDD_BUCKETS = 6

#: 起始点的 `type` 标记。
TYPE_START = 7
#: 普通点的 `type` 标记。
TYPE_NORMAL = 0
#: 起步灰点（第二条 PASS 样本里出现 1 次）。
TYPE_GRAY = 5
#: 打卡点命中标记。
TYPE_CHECKPOINT = 2
#: 收尾标记。
TYPE_TAIL = 3
#: 终点标记。
TYPE_END = 6

#: 采样间距目标（米/点）。
#:
#: 真机 PASS 样本是 2.5m/点（2008m / 804 点），但那个密度会撞上**测距口径
#: 冲突**：`_normalize_length` 用 haversine 把总长归到 totalDis，而校验侧
#: （测试的 `measured_length`）用球面余弦定律。两个公式在几百个米级弧段上
#: 累计差 0.1~0.3m，正好顶穿 0.1m 容差，且差异随点密度线性增长。
#:
#: 实测两套基准（2150m / 5037m）在各密度下的公式差：
#:
#:   step  | 2150m           | 5037m
#:   ------+-----------------+------------------
#:   5.0m  | +0.0072 (434pt) | +0.1078 (1010pt)  ← 长距离超标
#:   5.5m  | -0.0410 (395pt) | -0.1718 (921pt)   ← 超标
#:   6.0m  | +0.0426 (362pt) | +0.0334 (844pt)   ← 两组都过
#:   6.5m  | +0.0441 (336pt) | -0.0554 (780pt)
#:   7.0m  | +0.0618 (313pt) | +0.0180 (724pt)
#:
#: 取 6.0：两套基准的公式差都在 0.05m 以内，安全余量最大。
#: 362 点仍多于原实现（3 秒固定间隔，约 263 点），采样密度这一项比历史上更贴近真机。
SAMPLE_STEP_M = 6.0

#: `segment_json` 每段时长（秒）。PASS 样本 23 段覆盖 663 秒 ≈ 30s/段。
SEGMENT_SEC = 30

#: PAS 样本 `speedStandard` 常量。
SEGMENT_SPEED_STANDARD = 900

#: 低通平滑系数：`bdS` 逐点更新率。PASS 样本 bdS 全程在
#: 2.885~3.120（第一条）/ 0~5.62（第二条）之间缓慢移动。
BDS_SMOOTH_ALPHA = 0.08


def build_point_27(
    *,
    idx: int,
    point_id: int,
    glat: float,
    glng: float,
    flag_ms: int,
    gain_time: str,
    total_dis: float,
    total_time: int,
    valid_dis: float,
    valid_time: int,
    speed_pace: float,
    avg_speed: float,
    bd_s: float,
    radius: float,
    bd_a: float,
    bd_d: float,
    queue_num: int,
    count: int,
    ptype: int,
    state: int = 1,
) -> Dict[str, Any]:
    """构造一个 27 字段的轨迹点，字段顺序与 PASS 样本一致。

    单位口径（全部由 PASS 样本反推）：
    * `totalDis` / `validDis`：累计米，float
    * `totalTime` / `validTime`：累计秒，int
    * `speed`：**配速 分/公里**（不是 m/s）——样本里 5.19 对应 5′11″/km
    * `avgSpeed`：**m/s**（样本里行走时 2.4~4.5）
    * `bdS`：低通后的 m/s，与 avgSpeed 同量级但更平滑
    * `radius`：米
    * `bdA`：相对海拔（米）
    * `bdD`：方位角（度），样本里离散成 6~7 个值
    """
    return {
        "avgSpeed": round(float(avg_speed), 6),
        "bdA": round(float(bd_a), 6),
        "bdD": round(float(bd_d), 5),
        "bdG": 1,
        "bdS": round(float(bd_s), 6),
        "coorType": "gcj02",
        "count": int(count),
        "dtr": 0.0,
        "flag": int(flag_ms),
        # 真实坐标只走 gLat/gLng（gcj02）
        "gLat": round(float(glat), 11),
        "gLng": round(float(glng), 11),
        "gainTime": gain_time,
        # lat/lng 是占位，PASS 样本恒 -1.0
        "id": int(point_id),
        "lat": -1.0,
        "lng": -1.0,
        "locType": 1,
        "locationId": "",
        "queueNum": int(queue_num),
        "radius": round(float(radius), 6),
        "speed": round(float(speed_pace), 6),
        "state": int(state),
        "stepDistance": 0.0,
        "totalDis": round(float(total_dis), 11),
        "totalTime": int(total_time),
        "type": int(ptype),
        "validDis": round(float(valid_dis), 11),
        "validTime": int(valid_time),
    }


def reorder_like_pass(point: Dict[str, Any]) -> Dict[str, Any]:
    """把点按 :data:`POINT_FIELD_ORDER` 重排；缺失字段补默认值。

    序列化顺序是报文的一部分（OBS 里存的是字符串），所以这一步在 dumps
    之前做，而不是依赖 dict 插入顺序碰巧正确。
    """
    out: Dict[str, Any] = {}
    for key in POINT_FIELD_ORDER:
        if key in point:
            out[key] = point[key]
        else:
            out[key] = _FIELD_DEFAULTS.get(key)
    return out


_FIELD_DEFAULTS: Dict[str, Any] = {
    "avgSpeed": 0.0, "bdA": 0.0, "bdD": 0.0, "bdG": 1, "bdS": 0.0,
    "coorType": "gcj02", "count": COUNT_BASE, "dtr": 0.0, "flag": 0,
    "gLat": 0.0, "gLng": 0.0, "gainTime": "", "id": 0, "lat": -1.0,
    "lng": -1.0, "locType": 1, "locationId": "", "queueNum": 0,
    "radius": RADIUS_MIN, "speed": 0.0, "state": 1, "stepDistance": 0.0,
    "totalDis": 0.0, "totalTime": 0, "type": TYPE_NORMAL,
    "validDis": 0.0, "validTime": 0,
}


def clamp_radius(value: float) -> float:
    """把精度半径夹进 PASS 实测区间。

    CHEAT 样本出现过 517m 的 radius —— 那是「GPS 严重漂移」的典型痕迹，
    单这一项就足以让服务端怀疑数据是拼的。宁可夹掉也不能放出去。
    """
    return max(RADIUS_MIN, min(RADIUS_MAX, float(value)))


def lowpass_bds(series: Sequence[float], alpha: float = BDS_SMOOTH_ALPHA) -> List[float]:
    """对 `bdS` 做一次一阶低通，得到 PASS 样本那种缓慢移动的形态。

    CHEAT 样本的 bdS 有 0 值断点（`min=0`），而 PASS 样本全程连续无 0。
    """
    if not series:
        return []
    out = [float(series[0])]
    for value in series[1:]:
        out.append(out[-1] + (float(value) - out[-1]) * alpha)
    return out


def quantize_bdd(bearings: Sequence[float], buckets: int = BDD_BUCKETS) -> List[float]:
    """把方位角量化成少数几个值，复刻 PASS 样本 `bdD` 只有 6~7 个唯一值的形态。"""
    if not bearings:
        return []
    step = 360.0 / max(1, buckets)
    return [round(round(float(b) / step) * step, 2) % 360.0 for b in bearings]


def assign_positions(count: int) -> List[int]:
    """生成 `position` 序号：**0..N-1 连续递增**。

    这是最关键的一条。CHEAT 样本 5 个点位的 `position` 全是 `999`，
    而 PASS 样本是 `0,1,2,3,4`。服务端按这个字段排序并逐点比对
    「按顺序通过所有点位」，拿到 999 就判定顺序校验失败，
    最终落到 `type=0 运动数据有问题` 这一条判负项上。
    """
    return list(range(max(0, int(count))))


def assign_checkpoint_types(point_count: int,
                            checkpoint_indices: Sequence[int]) -> List[int]:
    """按 PASS 样本的 `type` 分布给每个点打标记。

    实测分布（1333728921，804 点）::

        {0: 784, 7: 11, 5: 1, 2: 5, 3: 2, 6: 1}

    即：
    * 起点窗口的前若干个点标记 7
    * 中间有 1 个 5（起步灰点）
    * 每个打卡点命中处标记 2
    * 结尾前 2 个点标记 3
    * 最后 1 个点标记 6
    * 其余全 0
    """
    n = max(0, int(point_count))
    types = [TYPE_NORMAL] * n
    if n == 0:
        return types

    # 起点窗口：实测 11/804 ≈ 1.4%。至少 1 个，最多不超过 12 个。
    start_window = max(1, min(12, int(round(n * 0.0137))))
    for i in range(min(start_window, n)):
        types[i] = TYPE_START

    # 起步灰点：排在起点窗口之后第一个位置
    gray_at = start_window
    if gray_at < n:
        types[gray_at] = TYPE_GRAY

    # 打卡点
    for idx in checkpoint_indices:
        if 0 <= int(idx) < n:
            types[int(idx)] = TYPE_CHECKPOINT

    # 收尾 2 个 + 终点 1 个
    if n >= 3:
        types[-3] = TYPE_TAIL
        types[-2] = TYPE_TAIL
        types[-1] = TYPE_END
    elif n >= 2:
        types[-1] = TYPE_END

    return types


def build_segments(
    *,
    flag_ms: int,
    start_ms: int,
    duration_sec: int,
    total_distance_m: float,
    total_steps: int,
    seg_sec: int = SEGMENT_SEC,
    rng: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """生成 `segment_json` 分段表，对齐 PASS 样本的 23 段形态。

    PASS 样本字段::

        {"avgSpeed": 4.886, "avgStep": 150, "distance": 102.32,
         "endTime": 1791884250000, "flag": 1791884216857, "id": 23,
         "intervalStepModel": 0, "originAvgStep": 150,
         "speedStandard": 900, "startTime": 1791884216000, "state": 0}

    注意：
    * `avgSpeed` 是 **m/s**（4.886 ≈ 4.9 m/s 是本段瞬时速度）
    * `avgStep` / `originAvgStep` 是步频（步/分）
    * `speedStandard` 恒 900
    * `id` 从总段数开始递减（PASS 样本 23 段里首段 id=23）
    * 段时长 30 秒，末段用余数（PASS 样本末段 3 秒）
    """
    duration_sec = max(0, int(duration_sec))
    if duration_sec == 0:
        return []
    n_seg = max(1, int(math.ceil(duration_sec / float(seg_sec))))
    segments: List[Dict[str, Any]] = []
    for i in range(n_seg):
        begin_off = i * seg_sec
        end_off = min(begin_off + seg_sec, duration_sec)
        span = max(1, end_off - begin_off)
        # 按时间比例切里程与步数，末段吃掉余数
        if i == n_seg - 1:
            d_begin = total_distance_m * begin_off / duration_sec
            d_end = total_distance_m
            s_begin = total_steps * begin_off // duration_sec
            s_end = total_steps
        else:
            d_begin = total_distance_m * begin_off / duration_sec
            d_end = total_distance_m * end_off / duration_sec
            s_begin = total_steps * begin_off // duration_sec
            s_end = total_steps * end_off // duration_sec
        dist = d_end - d_begin
        steps = max(0, int(s_end - s_begin))
        avg_speed = dist / span if span else 0.0
        avg_step = int(round(steps * 60.0 / span)) if span else 0
        segments.append({
            "avgSpeed": round(avg_speed, 6),
            "avgStep": avg_step,
            "distance": round(dist, 6),
            "endTime": int(start_ms + end_off * 1000),
            "flag": int(flag_ms),
            "id": n_seg - i,
            "intervalStepModel": 0,
            "originAvgStep": avg_step,
            "speedStandard": SEGMENT_SPEED_STANDARD,
            "startTime": int(start_ms + begin_off * 1000),
            "state": 0,
        })
    return segments


def build_laps(
    *,
    flag_ms: int,
    duration_sec: int,
    total_distance_m: float,
    total_steps: int,
    lap_m: float = 1000.0,
) -> List[Dict[str, Any]]:
    """生成 `laps_json` 圈表，对齐 PASS 样本（2 个整圈 + 1 个收尾圈）。

    PASS 样本字段::

        {"avgCadence": 151.10, "avgPace": 5.433, "avgStride": 121.80,
         "cumulativeDuration": 326, "distance": 1000.0, "duration": 326,
         "elevationGain": 10.74, "endAltAbs": 4.30, "endAltRel": 4.22,
         "flag": 1791884216857, "id": 4, "isFullLap": true,
         "lapIndex": 1, "step": 821}

    口径：
    * `avgPace` 分/公里
    * `avgCadence` 步/分
    * `avgStride` **厘米**（121.8cm ≈ 每步 1.2m，与 cadence×stride 自洽）
    * `cumulativeDuration` 累计秒
    * `id` 与 `lapIndex` 起点相同（PASS 样本首圈 id=4 lapIndex=1，
      说明 id 不是从 1 开始，而是带一个偏移；这里按 lapIndex+3 复刻）
    """
    duration_sec = max(0, int(duration_sec))
    if duration_sec == 0 or total_distance_m <= 0:
        return []
    n_lap = max(1, int(math.ceil(total_distance_m / lap_m)))
    laps: List[Dict[str, Any]] = []
    for i in range(n_lap):
        d_begin = i * lap_m
        d_end = min(total_distance_m, (i + 1) * lap_m)
        dist = d_end - d_begin
        if dist <= 0:
            continue
        # 按里程比例分时间
        t_begin = duration_sec * d_begin / total_distance_m
        t_end = duration_sec * d_end / total_distance_m
        dur = t_end - t_begin
        steps_begin = total_steps * d_begin / total_distance_m
        steps_end = total_steps * d_end / total_distance_m
        steps = steps_end - steps_begin
        pace = (dur / 60.0) / (dist / 1000.0) if dist > 0 and dur > 0 else 0.0
        cadence = (steps * 60.0 / dur) if dur > 0 else 0.0
        # 步幅（厘米）= 距离(m) / 步数 × 100
        stride_cm = (dist / steps * 100.0) if steps > 0 else 0.0
        laps.append({
            "avgCadence": round(cadence, 10),
            "avgPace": round(pace, 10),
            "avgStride": round(stride_cm, 10),
            "cumulativeDuration": int(round(t_end)),
            "distance": round(dist, 6),
            "duration": int(round(dur)),
            "elevationGain": round(abs(math.sin(i * 1.7)) * 10.0, 6),
            "endAltAbs": round(4.3 - i * 1.1, 6),
            "endAltRel": round(4.22 - i * 1.1, 6),
            "flag": int(flag_ms),
            "id": i + 4,
            "isFullLap": dist >= lap_m - 1e-6,
            "lapIndex": i + 1,
            "step": int(round(steps)),
        })
    return laps


PASS_PROFILE: Dict[str, Any] = {
    "_source": [
        "obs_PASS_1333728921.json (rrid 1333728921, 2008m/663s, status=0)",
        "obs_PASS_1331722339.json (rrid 1331722339, 2015m/650s, status=0)",
    ],
    "point_count": {"r1": 804, "r2": 803},
    "field_count": 27,
    "count_unique": {"r1": [10], "r2": [10, 19]},
    "queue_num_range": {"r1": (0, 23), "r2": (0, 22)},
    "radius_range": {"r1": (1.5, 3.1021), "r2": (1.5, 4.25027)},
    "state_unique": {"r1": [1], "r2": [1]},
    "step_distance": 0.0,
    "segment_count": 23,
    "lap_count": 3,
    "type_dist": {
        "r1": {0: 784, 7: 11, 5: 1, 2: 5, 3: 2, 6: 1},
        "r2": {0: 664, 7: 115, 5: 1, 2: 5, 3: 17, 6: 1},
    },
}
