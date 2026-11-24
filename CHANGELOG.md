# Changelog

本项目的所有重要变更都记录在这里。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

（暂无）

---

## [1.1.0] - 2026-11-24

把 v1.0.0 的「三项待补」做完，并修掉做完之后才暴露的两个自身缺陷。

### 新增

- **提交时同时写入两个 OBS key**
  详情页主路径 `run_data/{YYYYMMDDHH}/{uuid}.json` + 兜底
  `runData/{uid}/{sportType}/{startSec}_{uuid}.txt`。
  `recordUrl` 回填**详情页那个**。v1.0.0 只写兜底 key，App 拿不到轨迹
  → 画不出绿框 → 两天后复核判「轨迹无法归属到任何围栏」。

  > **小时目录用北京时间（UTC+8），不是 UTC。** 实测
  > `startTime=1795488715000` → UTC `02:51`、北京 `10:51`，真机样本落在
  > `run_data/2026112410/`。用 UTC 会算成 `02` 点，目录对不上，App 404。

  两个 key 的错误处理**故意不对称**：详情页 key 失败即中止（它是主路径），
  兜底 key 失败只告警（服务端按 `recordUrl` 关联，不影响结算）。

- **`avgPower` 真实值**（真机 2008m/663s → 223W）
  公式 `1.1 × 体重 × 速度(m/s)`，`DEFAULT_WEIGHT_KG = 68.0`。
  `realism=False` 时 `physio` 是空字典会退化成 0，故 `build_submission_payload`
  里再兜一次，保证关掉拟真也不漏。本机样本算出 227W，与真机差 1.8%。

  > **必须取整。** 服务端 `avgPower` 是 `i64`，发 `187.5` 时它截断成 `187`
  > 再重算签名，而我们的签名串里是 `"187.5"` —— 两侧拼串不同，直接
  > `10501 验证签名失败`。这种错 body 内部完全自洽，本地自检也查不出来。

- **`running/audit.py` — 跨记录体检**（`--audit`）
  把历史记录算成「像不像真人」的报告，补上单条报文自洽性**管不到**的纵向风险：
  单条再完美也挡不住「连续 6 天同一整点起跑」「每条都恰好 2000 米」。

  | 检查码 | 阈值 | 命中含义 |
  |---|---|---|
  | `AUDIT_STREAK` | ≥ 5 天 | 能画出一条直线 |
  | `AUDIT_HOUR` | ≥ 60% | 起跑时刻集中同一整点 |
  | `AUDIT_DIST_FLAT` | CV < 0.05 | 每条里程一样 |
  | `AUDIT_PACE_FLAT` | CV < 0.02 | 每条配速一样 |
  | `AUDIT_OVERLAP` | ≥ 90% | 两两轨迹同一条线 |
  | `AUDIT_REVERSE` | 反向 | 同线反跑（真人行为，只陈述） |
  | `AUDIT_MIDNIGHT` | 23 时 / 0 时 | 贴规则时段边界 |

  接入两处：`--audit` 单独出报告，`--run` 时在风控预检后顺带打一遍。
  **只提示、不拦截**，与 `riskguard` 的降级原则一致；任何异常都降级成
  一行「跳过」，绝不让辅助功能反过来挡住提交。

- **`test_audit.py`** — 21 项离线回归（机器人样本全命中、真人样本不误报、
  退化输入不崩）。

### 修复

- **`URL_RUN_RECORDS` 未导入**（新增代码自身的 bug）
  `client._log_cross_record_audit` 直接用了这个名字，但 `running/client.py`
  的 `from .config import (...)` 里没有它。后果是**每次 `--run` 都抛
  `NameError`，被外层 `try/except` 吃掉后打成一行「跨记录体检: 跳过」** ——
  功能看起来在跑，实际永远不生效。改为走既有的
  `history.get_run_records()`，并显式要 `page_size=50`。

- **`_print_audit` 探测了不存在的方法**
  原写法 `hasattr(client.history, "get_records")` —— `HistoryClient` 上
  这个方法叫 `get_run_records`。`hasattr` 恒为 `False`，于是每次都退到
  硬编码 URL 的分支，把 `https://run.gxapp.iydsj.com/...` 写死在 `cli.py` 里。
  改为直接调 `get_run_records`，URL 只留在 `history/config.py` 一处。

### 变更

- `--audit` 计入 `_no_explicit_action` —— 否则单独跑 `--audit` 会被当成
  「没有任何具体动作」，额外触发一次时钟同步。

### 已验证

| 项目 | 结果 |
|---|---|
| `pass_parity` | 25/25 × 2 基准 |
| `fence_parity` | 17/17，8 顶点逐点相同 |
| `test_audit` | 21/21 |
| `test_e2e_offline` | 15/15（两条断言按双 key 行为更新） |
| 全量离线用例 | 220 项，失败 2 项均为既有环境问题（见「已知限制」） |
| `detail_object_key(1795488715000)` | `run_data/2026112410/...`，与真机样本目录一致 |
| `avgPower` | 拟真开/关两条路径均为 227（真机 223） |

### 未验证

**双 key 写入还没有实机提交验证过。** 代码路径与 key 形态已对拍一致，
但「App 里当天记录是否出现绿框」只能靠真机看一眼。这是 v1.1.0 唯一
悬着的结论。

---

## [1.0.0] - 2026-11-24

首个可运行版本。核心成果：**定位并修复「记录被判作弊 / 两天后失效」的完整因果链**，
并用独立客户端成功提交了一条 `status=0` 通过记录。

### 新增

- **`running/pass_form.py`** — PASS 形态生成器。全部常量从两条真机通过样本
  （804 / 803 个点）反推，不是推测值：
  - 27 字段点结构（`avgSpeed bdA bdD bdG bdS coorType count dtr flag gLat gLng
    gainTime id lat lng locType locationId queueNum radius speed state
    stepDistance totalDis totalTime type validDis validTime`）
  - `count` 恒 10、`queueNum` 0..23 循环、`radius` 夹在 1.5~3.1、`state` 恒 1、
    `stepDistance` 恒 0、`flag` 全场同值
  - `bdS` 一阶低通平滑、`bdD` 量化 6 档
  - `segment_json` 分段表（30 秒一段）、`laps_json` 圈表
- **`pass_parity.py`** — 离线对拍：25 项检查 × 2 条真机基准样本
- **`fence_parity.py`** — 围栏回显对拍：17 项检查，含 8 个顶点逐点比对
- **`final_check.py`** — 提交前人工核查，打印报文全部关键指标
- **`dry_run.py`** — 干跑：走完阶段 1/2/3（拉规则、风控预检、生成报文、本地自检），
  **不进入**等待与上传提交。报文与 `--run` 逐字节相同
- **`live_probe.py`** — 拉取并打印实时规则 / 围栏 / 打卡点明细
- **`obs_fetch.py` / `obs_unbox.py`** — 下载并解包 OBS 原始明细（gzip+base64 双层）
- **`verdict_probe.py` / `risk_probe.py`** — 逐条拉详情看判据、四个风控面全量体检
- **`fix_obs_fence.py`** — 修复已提交记录的 OBS 明细（围栏字段 + run_data 结构）
- **`logout_account.py`** — 调用服务端 `POST /api/v6/user/logout` 真正退登，
  fail-closed：服务端未明确返回 `error=10000` 就不删本地凭据
- **`FINDINGS.md`** — 技术结论汇总：加密栈、`isValidPoint` 反汇编、判罚链路证据链

### 修复

- **`position` 全 999 导致判作弊**（`9ed8de8`）
  真机通过样本的 `position` 是 `0,1,2,3,4` 连续序号，我们之前发的是 `999`。
  服务端按它排序并比对「按顺序通过所有点位」，拿到 999 就无从排序，
  落到 `type=0 运动数据有问题` 这条兜底判负项上。
  **这是账号 17 条记录里 15 条被判作弊的机械原因，与配速快慢无关。**

- **围栏回显为空**（`9ed8de8`）
  `geoFencesJson` 一直是 `[]`，围栏 id 与 8 个顶点根本没发出去。
  真机的真实围栏 id 只出现在 `geoFencesJson[0].id` 里。

- **围栏顶点字段名错误**（`d929822`）
  服务端**下发**用 `glon`/`lon` + `pointsNumber`，真机**回传**用 `glng`/`lng`
  且无 `pointsNumber`、条目多一个 `distance: 0.0`。直接 dump 下发 raw
  会让服务端按 `glng` 取到空值 → 围栏多边形落空 → App 画不出绿框。
  新增 `build_geo_fences_json()` 统一归一化。

- **`run_data` 结构错误**（`a0e379f`）
  真机是对象 `{"allLocJson": "<点数组JSON字符串>", "useZip": false}`，
  我们发的是裸点数组。App 读 `run_data.allLocJson` 在 list 上取到 `null`，
  **轨迹画不出、围栏绿框也画不出**。这是绿框问题的最终根因。

- **中文被转义**
  `json.dumps` 默认 `ensure_ascii=True`，把「围栏2」写成 `\u56f4\u680f2`。
  真机走 Gson 输出 UTF-8 原文。改后长度从 637 降到 627 字符。

- **两个 `runAreaId` 取值混乱**
  真机报文里是两个不同值：`fivePointJson` envelope 里是 `-1`，
  `save_record` 顶层是真实围栏 id。之前共用一个参数，两种形态都与真机不符。

- **`distance()` 的 `acos` 零点缺陷**
  球面余弦定律在两点重合时浮点给出 `0.9999999999999999`，
  `acos` 乘地球半径得到 **0.0949 米** —— `distance(p, p)` 不是 0。
  后果是「打卡点必须落在轨迹上」的判据永远不成立。改回 haversine。

- **采样密度与测距口径冲突**
  采样加密到 2.5m/点后，haversine 与球面余弦在 2150m 上累计差 0.12m，
  顶穿 0.1m 容差。实测找到 6.0m 间距（362 点）时两组基准都落在 0.05m 内。

- **`_restore_length` 锚点导致里程发散**
  把打卡点当 anchors 传给绕首点的相似变换会让相似性失效，
  实测 2150m 被推到 **4191m**，随后在同一批点之间算出 **248 m/s** 的瞬时速度。

- **`_jitter_timestamps` 首尾写死 3000ms**
  采样变密后首尾抖动幅度过大，瞬时速度飙到 225 m/s。改用真实间隔中位数兜底。

### 已验证

| 项目 | 结果 |
|---|---|
| 真机 PASS 对拍 | 25 项检查 × 2 基准，全过 |
| 围栏回显对拍 | 17 项，含 8 顶点逐点相同 |
| `test_run_consistency` | 23/23 |
| `test_e2e_offline` | 15/15 |
| `test_crypto` | 9/9 |
| `test_realism` | 30/30 |
| 实机提交 | `rrid=1374320373`，`status=0` 通过，5 条判据全绿 |

### 已知限制

- `test_config.py` 有一条目录名断言失败（解压目录不叫 `7.3.92`），属环境问题
- `test_pace_display.py` 在 Windows 上因 GBK 解码 Node 输出失败，与本项目逻辑无关
- 网络栈是 `urllib` + OpenSSL，无 OkHttp 的 JA3 指纹，服务端若做 TLS 指纹比对无法自证

---

## 版本号说明

主版本号只在**报文协议层不兼容变更**时递增（例如服务端升级导致加密栈或字段语义改变）。
修复类变更递增次版本号，纯文档/工具递增修订号。
