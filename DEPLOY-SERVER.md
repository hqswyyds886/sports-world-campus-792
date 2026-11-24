# 运动世界校园 Web 控制台 — 部署说明

**线上地址**：http://120.25.197.216:8420/

部署于 2026-11-24，版本 v1.1.0。

---

## 一、服务器布局

| 项 | 值 |
|---|---|
| 主机 | 120.25.197.216（阿里云 ECS，华南1深圳，`ecs.e-c1m1.large`） |
| 系统 | Ubuntu 24.04.5 LTS · Python 3.12.3 · 2 核 1.7G · 40G |
| 源码 | `/opt/sport-campus` |
| 数据 | `/var/lib/sport-campus`（`ZJWH_DATA_DIR`） |
| 服务 | systemd `sport-campus` |
| **对外端口** | `0.0.0.0:8420`（nginx，**Basic Auth**） |
| **内部端口** | `127.0.0.1:8421`（webui.py，仅本机） |
| 日志 | `/var/log/sport-campus.log` |

**与 kaoyan 站完全隔离**：kaoyan 走 nginx `80 → 127.0.0.1:8001`，
本项目走 nginx `8420 → 127.0.0.1:8421`，两条 server 块互不相干。

### 架构

```
浏览器 ──Basic Auth──> nginx:8420 ──> 127.0.0.1:8421 (webui.py)
```

认证**故意放在 nginx 而不是 Flask 里**：

* `webui.py` 是上游源码，升级时整目录替换 —— 认证写进去下次升级就没了
* nginx 只绑 `8420`，webui 只绑 `127.0.0.1`，nginx 挂了也不会裸奔
* 顺带能加限流（同 IP 每分钟 20 次认证尝试）

---

## 二、登录凭据

| 项 | 值 |
|---|---|
| 用户名 | `fh` |
| 密码 | 见服务器 `/etc/nginx/.htpasswd-sport`（apr1 哈希，不可逆） |
| 认证文件 | `/etc/nginx/.htpasswd-sport`（root:www-data 640） |

**改密码**：

```bash
printf '%s\n' '新密码' | openssl passwd -apr1 -stdin | \
  sed 's/^/fh:/' > /etc/nginx/.htpasswd-sport
chmod 640 /etc/nginx/.htpasswd-sport
chown root:www-data /etc/nginx/.htpasswd-sport
systemctl reload nginx
```

---

## 三、日常运维

```bash
systemctl status  sport-campus     # 看状态
systemctl restart sport-campus     # 重启
journalctl -u sport-campus -n 50   # 若日志文件被清
tail -f /var/log/sport-campus.log  # 实时日志
```

已 `systemctl enable`，**开机自启**。

---

## 三、升级流程

本地改完代码 → 重新打包上传 → 替换 `/opt/sport-campus` → 重启。
数据目录 `/var/lib/sport-campus` 不动，所以 `.session.json`（登录态）和
`state/`（跑批账本）都会保留，升级不需要重新登录。

```bash
# 本地
cd C:/Users/fh/sports/refs/xiaoyuan
tar czf /tmp/sport.tgz --exclude='.git' --exclude='node_modules' \
  --exclude='__pycache__' --exclude='obs_*.json' --exclude='state/*' \
  --exclude='.session.json' shijie-yundong-xiaoyuan-main

# 上传后（在服务器上）
cd /opt && rm -rf sport-campus.new
tar xzf /tmp/sport.tgz -C /opt
cd shijie-yundong-xiaoyuan-main && cp -a . /opt/sport-campus.new
mv /opt/sport-campus /opt/sport-campus.old && mv /opt/sport-campus.new /opt/sport-campus
systemctl restart sport-campus
```

**配置不在源码目录里**，在 `/var/lib/sport-campus/config.ini`：

```ini
[webui]
host = 127.0.0.1     # 只绑本机，对外由 nginx 承担
port = 8421          # 内部端口；对外是 nginx 的 8420

[session]
session_file = .session.json
```

> 踩过的坑：`config_loader` 的 `_CONFIG_PATH = _DATA_DIR / "config.ini"`，
> 而 `_DATA_DIR` 优先取环境变量 `ZJWH_DATA_DIR`。systemd 里设了它，
> 所以放在 `/opt/sport-campus/config.ini` 的配置**完全不会被读**，
> 端口会静默回退到 `127.0.0.1:9999`。

---

## 四、网络放行（两层，缺一不可）

排查时踩了坑：只加阿里云安全组不够，服务器自己的 ufw 也要放行。

| 层 | 规则 |
|---|---|
| 阿里云安全组 `sg-wz99mlsd1pl9wkz2rvnw` | 入方向 允许 / 自定义 TCP / `0.0.0.0/0` / `8420/8420` |
| 服务器 ufw | `ufw allow 8420/tcp` |

`ufw` 默认拒绝入站，`8420` 不在原清单里（原本只有 22/80/443/8001），
所以只开安全组时外网仍然连不上。

**8421 不需要放行任何一层** —— 它只监听 `127.0.0.1`，外部本就连不上。

---

## 五、安全状态

| 项 | 状态 |
|---|---|
| `8420` 无凭据访问 | **401** 已拦 |
| `8420/api/*` 无凭据 | **401** 已拦 |
| 错误密码 | **401** 已拦 |
| 正确凭据 | 200 |
| `8421` 外网可达性 | 不可达（只绑 127.0.0.1） |
| 认证爆破防护 | 同 IP 每分钟 20 次（`limit_req zone=sport_auth`） |

认证在 nginx `server` 层，所有 `location` 自动继承 —— 新加路由不会漏掉。

---

## 六、已验证

| 项 | 结果 |
|---|---|
| 外网 8420 无凭据 | 401 |
| 外网 8420 正确凭据 | 200 |
| 外网 8420 错误密码 | 401 |
| 外网 `/api/status` 无凭据 | 401 |
| 外网 `/api/status` 带凭据 | 200，`{"logged_in":false,...}` |
| 8421 外网 | 不可达（正确） |
| kaoyan 站首页 | 200（未受影响） |
| kaoyan `/api/health` | 200，`version=2.0`（未受影响） |
| `systemctl is-active` | sport-campus / nginx / kaoyan 均 active |
| `systemctl is-enabled` | sport-campus = enabled（开机自启） |

---

## 七、待办

- 双 OBS key 写入尚未实机提交验证 —— 在控制台跑一次后，
  去 App 看当天记录有没有绿框。这是 v1.1.0 唯一悬着的结论。
