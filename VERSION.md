# 版本信息

当前版本。CHANGELOG.md 记录变更历史，本文件记录**结构化的版本元数据**，
供脚本与外部工具读取。

```toml
[version]
current     = "1.0.0"
released    = "2026-11-24"
target_app  = "7.3.92"
protocol    = "NetSecKit 4.2.4"
```

## 兼容性矩阵

| 客户端版本 | 目标 App | 协议 | 状态 |
|---|---|---|---|
| 1.0.0 | 7.3.92 | NetSecKit 4.2.4 | 已验证（实机提交通过） |

## 校验和

首个版本的报文形态基准来自两条真机通过样本，样本不进仓库（含真实记录），
但特征值记录在这里便于复核：

| 样本 | 点数 | 分段 | 圈 | 用途 |
|---|---|---|---|---|
| `obs_PASS_1000000015` | 804 | 23 | 3 | PASS 形态基准 A |
| `obs_PASS_1000000018` | 803 | 22 | 3 | PASS 形态基准 B |
| `obs_CHEAT_1000000006` | 198 | 0 | 3 | 反例（position=999） |
| `obs_CHEAT_1000000005` | 198 | 0 | 3 | 反例（position=999） |

## 验证命令

```bash
# 离线对拍（不联网）：25 项 × 2 基准
python pass_parity.py

# 围栏回显对拍（不联网）：17 项
python fence_parity.py

# 提交前人工核查（不联网）
python final_check.py

# 干跑（联网拉实时数据，不提交）
python dry_run.py

# 回归
python test_run_consistency.py
python test_e2e_offline.py
python test_crypto.py
python test_realism.py
```
