# 逆向结论与报文形态对齐记录

这份文档记录本次工作的**核心技术结论**：服务端为什么判「作弊」、判据是什么、
报文该长什么样。代码只是结论的实现，读这份比读代码快。

样本：`运动世界_7.3.92.apk`（330,104,718 字节）
SHA256 `27a3d5064fa485984ff35b22a42639512c67f1726169b76ffa41f4e0191f1439`

---

## 一、协议的加密栈（NetSecKit 4.2.4）

```
请求信封  {"d":"<AES密文b64>","h":"<MD5>","k":"<RSA加密的AES key>","p":"101","t":"0"}
内层明文  {"data":"<业务JSON b64>","keyDataFour":"…","keyDataOne":"…",
           "keyDataThree":"…","keyDataTwo":"…","platform":2,"timeStamp":<秒>}\n
响应信封  {"r":"<AES密文b64>","s":"<RSA签名b64>","v":101}
```

- AES-128-CBC，**IV 全零**（不是随机）
- 每次请求随机 16 位 AES key，用 RSA-1024 公钥 PKCS#1 v1.5 加密后放 `k`
- 内层 JSON 字段顺序与末尾换行都不能改，否则 `h` 对不上
- 响应 key 由四段 keyData 经自定义 feistel KDF 派生（`byte_hash → feistel → final_mix`）
- 签名盐 `2slhe02lsfiwowlcixisla_sls-_slaor`

## 二、关键接口

| 用途 | 路径 |
|---|---|
| 安全初审 | `POST /api/v65/security/checkGeeUse` |
| 极验绑定 | `POST /api/v70270/security/geevalidate` |
| 登录 | `POST /api/v70100/login`（Basic Auth） |
| 跑步规则 | `POST /api/v70103/runModePolicy` |
| 电子围栏 | `POST /api/v1/getGeoFenceForRun` |
| 打卡点位 | `POST /api/v560/get/1/distance/{米}` |
| 提交成绩 | `POST /api/v70260/runnings/save/record` |
| OBS 换签名 | `POST /api/obs/temporary/url` |
| 历史列表 | `POST /api/v70230/runnings/records` |
| 单条详情 | `POST /api/v70320/runnings/get_one_record` |
| 作弊特征库 | `POST /api/v78/cheat/cheatlist` |
| 信用分 | `GET /api/creditscore/v70390/popup?taskType=2` |
| 无障碍策略 | `GET /api/v1/barrierFree/getBarrierFree` |
| 控制信令 | `GET https://control.gxapp.iydsj.com/getMessage` |

宿主 `run.gxapp.iydsj.com` / `discovery.gxapp.iydsj.com` / `datapoint.gxapp.iydsj.com`

## 三、设备锁：10121 与 DeviceId

新设备登录直接返回：

```
10121 登录失败，此账号已在其他设备登录，因账号保护机制，原状态未退出
```

`DeviceId` 是服务端认设备的唯一凭据，**32 位小写十六进制**，不能带横线，
大小写不同算两台设备（服务端做字符串比对，且整个 headers 参与签名）。

真机值可从 APK 数据目录取到：

```
/data/data/com.zjwh.android_wh_physicalfitness/files/.imprint
```

文件尾部有一个 32 位 hex，就是 DeviceId。需要 root（本机用 KernelSU）。

## 四、反作弊打分函数 isValidPoint

`lib/arm64-v8a/libswsport.so` 里的 JNI：

```
Java_com_zjwh_sw_sport_SportJniUtils_isValidPoint    偏移 0x10e84，388 字节
```

用 capstone 精确反汇编后还原（ARM64，入参 `w2` 模式、`w3` 计数、`s0`/`s1` 浮点）：

```
基础分 w8：按 w3 分档
    w3 < 3        → 0
    3 ≤ w3 < 5    → 5
    5 ≤ w3 < 8    → 15
    8 ≤ w3 < 15   → 25
    w3 ≥ 15       → 30

模式分 w9：w2 == 1 → 30，w2 == 2 → 15，否则 20

距离分 w10：比较 s1（米）
    s1 < 10        → 30
    10 ≤ s1 < 50   → 20
    50 ≤ s1 < 100  → 10
    s1 ≥ 100       → 0

时间分 w11：s0 > 0 → 10，否则 0

总分 = w8 + w9 + w10 + w11
valid = (总分 > 65) && (w4 & 0xFF != 0) && (w5 & 0xFF == 0)
```

**硬结论**：越过 65 分要求基础分 ≥ 25，即 `w3 ≥ 8`。

`.rodata` 里的两个阈值常量实测为 `C = 50.0`、`D = 100.0`（0x42480000 / 0x42c80000）。

## 五、真正的判罚链路（从真实记录反推）

同一账号 17 条记录里 15 条 `status=2`（判作弊）。逐条拉详情后，判负项只出现在一条：

```
type=9   按顺序通过所有点位      completeStatus=1
type=1   最少要跑2.00公里        completeStatus=1
type=7   跑5分钟以上             completeStatus=1
type=11  步频控制在60-300步/分钟  completeStatus=1
type=12  配速控制在3′00″-10′00″  completeStatus=1
type=0   运动数据有问题          completeStatus=0   ← 唯一判负项
```

里程、配速、步频、点位顺序**全部通过**，只有一条兜底判负。那说明问题不在这些
可解释的指标上，而在报文本身的形态。

### 直接比对 OBS 原始明细

`run_data/{YYYYMMDDHH}/{uuid}.json` 是 gzip+base64 双层的，解出来后
`fixed_point_json` 内层是关键：

**通过的记录**
```
id=6  position=0  isFixed=0  田径场2
id=7  position=1  isFixed=0  田径场5
id=8  position=2  isFixed=0  田径场1
id=9  position=3  isFixed=1  田径场3
id=10 position=4  isFixed=0  田径场6
```

**判作弊的记录**
```
id=1  position=999  ...
id=2  position=999  ...
（5 个点全是 999）
```

`position` 是服务端排序「按顺序通过所有点位」的依据。999 是无效占位值，
拿到它就没法排序，于是落到 `type=0 运动数据有问题`。

**这就是「判定作弊」的机械原因，与配速快慢无关。**

### 其他字段鸿沟（PASS vs CHEAT 逐点统计）

| 字段 | PASS | CHEAT | 说明 |
|---|---|---|---|
| 轨迹点数 | 804 / 803 | 198 | 采样密度差 4 倍 |
| `count` | 恒 10 | 20~88 乱跳 | 真机是常量 |
| `queueNum` | 0~23 | 恒 0 | 真机有队列深度 |
| `radius` | 1.5~3.1 | 最大 **517** | 荒谬的精度半径 |
| `bdS` | 平滑无 0 | 有 0 值断点 | 低通后的速度 |
| `bdD` | 6~7 个唯一值 | 连续 | 方位角离散化 |
| `segment_json` | 完整 22~23 段 | 空 | 真机有分段表 |
| `laps_json` | 3 圈 | 空 | 真机有圈表 |
| 点字段数 | **27** | 6 | 真机结构 |

## 六、真机的 27 字段点结构

```
avgSpeed bdA bdD bdG bdS coorType count dtr flag gLat gLng gainTime
id lat lng locType locationId queueNum radius speed state stepDistance
totalDis totalTime type validDis validTime
```

关键点：

- `lat` / `lng` **恒为 -1.0**（占位，服务端不读）
- 真实坐标在 `gLat` / `gLng`，坐标系由 `coorType` 声明为 `gcj02`
- `speed` 是**配速 分/公里**（不是 m/s）；`avgSpeed` 才是 m/s
- `flag` 全场同一个值 = 本场起始毫秒戳
- `stepDistance` 恒 0.0，`state` 恒 1
- `totalDis` / `validDis` / `totalTime` / `validTime` 单调不减
- `type` 分布：起点窗口 7、起步灰点 5、打卡命中 2、收尾 3、终点 6、其余 0

## 七、两个 runAreaId 取值不同

真机报文里它们是两个不同的值：

```
fivePointJson envelope 里的 runAreaId  →  -1
save_record 顶层 runAreaId             →  真实围栏 id
```

真实围栏 id 只出现在 `geoFencesJson[0].id` 里。早先两者共用一个参数，
只能同时 -1 或同时真实 id，两种都与真机不符。

## 八、两个容易踩的数值坑

### 1. `acos` 的零点缺陷

球面余弦定律写成 `acos(sin·sin + cos·cos·cos(Δλ))`。两点重合时括号里数学上
是 1，但浮点给出 `0.9999999999999999`；`acos` 得到 1.49e-8 弧度，
乘地球半径 6371000 = **0.0949 米**。

也就是说 `distance(p, p)` 不是 0，是 9.5 厘米。后果是「打卡点必须落在轨迹上」
的判据永远不成立。

**必须用 haversine**：`sin(Δ/2)²` 在两点重合时是精确 0，`asin(0) = 0`。

### 2. 采样密度 × 测距口径

采样间距决定「用两个公式算出的里程能差多少」：

| 采样间距 | 2150m 时两公式差 | 5037m 时 |
|---|---|---|
| 2.5m | 0.12m | — |
| 5.0m | 0.007m | 0.108m |
| **6.0m** | **0.043m** | **0.033m** |
| 7.0m | 0.062m | 0.018m |

服务端容差是 0.1%。取 6.0m 时两套口径都落在容差内。

## 九、验证方式

```bash
# 离线对拍（不联网）：25 项检查 × 2 条真机基准样本
python pass_parity.py

# 干跑（联网拉实时规则，但不提交）：打印报文全部关键指标
python dry_run.py

# 提交前人工核查
python final_check.py
```

`pass_parity.py` 的基准样本需要自行抓取（见 `obs_fetch.py` 与 `obs_unbox.py`），
仓库不含真实记录数据。

## 十、参考

- [Inverx/com.zjwh.android_wh_physicalfitness](https://github.com/Inverx/com.zjwh.android_wh_physicalfitness) — 协议资料
- [IRmsk/pace-forge](https://github.com/IRmsk/pace-forge) — Rust 实现，判据与单位口径的交叉验证来源

## 免责声明

仅供网络协议学习与安全研究。请遵守所在学校规定与相关法律法规，
因使用本代码产生的一切后果由使用者自行承担。
