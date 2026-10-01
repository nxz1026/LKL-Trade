# Trade HTTP API 协议

> LKL-Trade v2.1+ — 决策/结果 HTTP 交换协议

## 概述

HTTP 模式通过 Oracle 端的 **emotion-core presentation 层**（Python 标准库 `http.server`）实现决策拉取和结果回传，替代原有的 SFTP 文件传输方式。holdings 和 manual_orders 仍通过 SFTP 传输。

**服务端架构：**
- emotion-core `presentation/server.py` — 路由注册 + 请求分发
- emotion-core `presentation/trade_api.py` — Trade API handler 模块
- nginx `/trade/` 反代到 `http://127.0.0.1:8098/api/trade/`
- 决策生成：`strategy_signal` 表 → `gen_decisions.py` → Trade API handler

## 启用方式

客户端 `config.env` 设置：

```
GM_REMOTE_URL=https://140.83.62.161/trade
GM_SSL_VERIFY=false
```

设置后 `process_once()` 自动走 HTTP 模式；未设置时回退 SFTP 模式。

> ⚠️ **启用前必读**
>
> 1. **HTTP 模式不区分用户** — 服务端为单一 `state.json` 与全局 `processed`。
>    多账户并发时 N 个客户端会拿到同一 `batch_id`，各下真单但仅第 1 笔被记录，
>    其余 N-1 笔**永久丢失且无任何报错**。单账户无此问题。详见「多用户限制」。
> 2. **端点当前对公网无鉴权可达** — 详见「安全现状」。

## 端点

### GET /decisions?date=YYYY-MM-DD

拉取指定日期的决策批次。

**请求参数：**
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date` | string | 否 | 决策日期（Asia/Shanghai），默认当天 |

**响应 200：**
```json
{
  "batch_id": "1a0960df-77c4-4aa2-8b4c-5891a2ecaeeb",
  "for_date": "2026-09-30",
  "actions": [
    {
      "action": "BUY",
      "code": "000504",
      "volume": 100,
      "exec": "OPEN_POS",
      "reason": "ma_golden_cross score=78"
    }
  ]
}
```

**空决策：** 当日无 BUY 信号时返回 200 + 空 `actions` 数组。

**响应 400：** `date` 非 ISO 格式 → `{"error": "invalid date: ..."}`

- `exec` 是**执行分发依据**（`OPEN_POS`↔`BUY`、`CLOSE_ALL`↔`SELL`），缺失时客户端按 `action` 兜底
- `batch_id` 是全局唯一标识（UUID），客户端用于幂等追踪
- 同日期多次拉取返回相同 `batch_id`（决策未刷新时）
- 决策刷新后生成新 `batch_id`
- `volume` 目前由策略侧**固定下发 100 股**（`trade_api.py` 中硬编码），不随股价变化

### POST /results

回传执行结果。

**请求体：**
```json
{
  "batch_id": "1a0960df-77c4-4aa2-8b4c-5891a2ecaeeb",
  "for_date": "2026-09-30",
  "trades": [
    {
      "ref": "2026-09-30|000504|BUY",
      "action": "BUY",
      "code": "000504",
      "ok": false,
      "price": 0,
      "shares": 0,
      "order_id": "",
      "status": "REJECTED",
      "status_label": "已拒绝",
      "reason": "非交易日或不在盘中时段，暂停自动下单",
      "note": "ma_golden_cross score=78",
      "traded_at": "2026-09-30T13:35:25"
    }
  ]
}
```

**响应 200（首次提交）：**
```json
{"status": "ok", "batch_id": "1a0960df-77c4-4aa2-8b4c-5891a2ecaeeb"}
```

**响应 200（重复提交，幂等）：**
```json
{"status": "ok", "batch_id": "1a0960df-77c4-4aa2-8b4c-5891a2ecaeeb", "note": "idempotent"}
```

**响应 400：** JSON 解析失败（`{"error": "invalid JSON: ..."}`）

- 结果写入 Oracle `~/trade/results_{for_date}_{timestamp}.json`
- 对应 `batch_id` 标记为已处理（幂等）
- 重复 POST 同一 `batch_id` 返回 `note: "idempotent"`，不产生新结果文件

### GET /results?date=YYYY-MM-DD

获取指定日期最新执行结果（供策略端/DB 消费）。

**响应 200：**
```json
{
  "batch_id": "1a0960df-77c4-4aa2-8b4c-5891a2ecaeeb",
  "for_date": "2026-09-30",
  "trades": [...]
}
```

**响应 200（当日无结果）：**
```json
{"for_date": "2026-09-30", "trades": []}
```

> 实测为 `200` + 空 `trades`，**不是 404**。客户端不应依赖 404 分支。

### GET /health

健康检查。

**响应 200：**
```json
{"ok": true, "service": "emotion_core_trade_api"}
```

## 幂等保证

### 客户端

- `processed_batches.json` 记录已处理的 `batch_id` 集合
- `process_once()` 执行前检查 `is_processed(batch_id)`，已处理则跳过
- 执行成功后标记 `mark_processed(batch_id)`

### 服务端

- `state.json` 记录当前决策 `batch_id` 和已处理 `batch_id` 集合
- 重复 POST 同一 `batch_id` 不产生新结果文件
- 决策刷新时生成新 `batch_id`，旧 `batch_id` 不会被覆盖

### 去重对比

| 模式 | 去重机制 | 层数 |
|---|---|---|
| SFTP | ledger + intent + _consumed_archived + by_ref + pull newest-only | 5 层 |
| HTTP | batch_id 集合 | 1 层 |

## 错误处理

| HTTP 状态码 | 含义 | 客户端行为 |
|---|---|---|
| 200 | 成功 | 正常处理；`actions` / `trades` 为空数组即"无数据" |
| 400 | 请求格式错误（`invalid date` / `invalid JSON` / `empty body` / `missing batch_id or for_date`） | 告警，不重试 |
| 500 | 服务端错误 | 告警，下次轮询重试 |
| 网络不可达 | 连接失败 | 告警，回退等待 |

> **实测不会返回 404。** "无结果"同样是 `200` + 空 `trades`。客户端不应依赖 404 分支。
> 另：POST 空 body 也会得到 400（`empty body`），不只是 JSON 解析失败。

## nginx 配置（Oracle 端）

```nginx
location /trade/ {
    proxy_pass http://127.0.0.1:8098/api/trade/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 64k;
}
```

客户端访问 `https://140.83.62.161/trade/decisions?date=...`
等价于 `http://127.0.0.1:8098/api/trade/decisions?date=...`。

## 安全现状（2026-10-01 实机核对）

以下为**已知并接受的当前状态**，记录于此以免后续误判。核对方式：从公网无凭据直连实测。

### 边界在哪

| 层 | 实际状态 |
|---|---|
| nginx | `/trade/` **未配置 `auth_basic`**（同文件的 `/emotion/`、`/dashboard/`、`/resume/`、`/admin/` 均已配置）；`client_max_body_size 64k` 限制了请求体大小 |
| 应用层 | `trade_api.py` 无任何鉴权、限流、CSRF 校验 |
| 客户端 | `remote_http.py` 两个调用均不带任何 header |
| 服务端口 | dashboard 绑定 `0.0.0.0:8098` |
| 云安全组 | 8098 对公网**不可达**（已实测），但 443 可达 |
| iptables | `INPUT policy ACCEPT` 且含一条 `ACCEPT all` 兜底规则，其后的 SSH/REJECT 为**死规则**，实际不提供任何防护 |

**净结论：系统内不存在任何针对本端点的访问控制。**
唯一实际起作用的边界是 **OCI 云安全组**——它挡住了 8098 的公网直连，但 443 是放开的，
而 nginx 的 `/trade/` 恰好把交易 API 重新暴露在 443 上。
已实测：无凭据从公网 `GET /trade/health` 返回 200。

### 早期表述中的假设已不成立

本节早期版本写有：

> 服务端绑定 127.0.0.1，仅 nginx 反代暴露
> 无认证头（内网/VPN 场景）

两条都与实机不符：服务端口实绑 `0.0.0.0`（`ss` 实测）；
`140.83.62.161` 是**公网 IP 且无 VPN**。
"不做鉴权"在原假设（内网/VPN）下是合理取舍，问题是部署时该假设未成立。

### TLS

nginx 使用自签证书（`CN=140.83.62.161`，SAN 含该 IP，有效期至 2036-09-11）。
客户端默认 `GM_SSL_VERIFY=false` —— **不校验证书**。这意味着链路可被中间人读写：
决策指令可被篡改，且未来的任何凭据若走此链路同样可被窃取。
若后续引入鉴权令牌，**必须同时修复证书校验**，否则令牌等同于明文。

### 流量现状

> **查日志的正确位置**：站点配置了 `access_log /var/log/nginx/dsh-timing.log dsh_timing;`
> （`dsh-web` 第 31 行），**覆盖** `nginx.conf` 的默认 `access.log`。
> 本端点的访问记录在 `dsh-timing.log` 及其轮转文件中，**不在 `access.log`**。

实测结果：

- 更早的轮转日志（`dsh-timing.log.2.gz` 及以前）：`/trade/` 命中数 **0** —— 端点为 2026-09-30 新建
- `dsh-timing.log.1`：2026-09-30 一整天的联调流量，来源 `183.222.0.206`，
  UA 覆盖 `python-requests` / `curl` / `PowerShell`。内容包括 health 轮询、
  decisions/results 往返、非法 `date` 与路径穿越类输入的验证。
  其中注入类输入（`DROP TABLE strategy_signal`、`' OR '1'='1`、`../../../etc/passwd`）
  **均被正确拒绝（400）**，可佐证本端点无 SQL 注入与路径穿越。

除该次联调外无持续流量 —— 该链路**尚未投入日常使用**。

## ⚠️ 多用户限制：HTTP 模式无用户维度

**这是 HTTP 模式当前最实质的功能缺陷，优先级高于鉴权问题。**

SFTP 模式通过 `GM_REMOTE_DIR=userN` 为每个用户提供独立目录。HTTP 模式（v2.1 引入）
**没有继承该维度**：

| | SFTP 模式 | HTTP 模式 |
|---|---|---|
| 决策隔离 | 每人 `userN/` 独立目录 | **无**——`GM_REMOTE_URL` 单端点，无 user 参数 |
| 服务端状态 | 各自目录 | **单一** `state.json`、单一 `decisions[for_date]` 缓存、单一全局 `processed` |
| 批次 ID | 天然隔离 | **所有人拿到同一个 `batch_id`** |

### 多个账户同时使用时的后果

1. N 个客户端 GET 同一日期 → 命中同一缓存 → **N 个客户端拿到同一个 `batch_id`**
2. 各自本地的 `processed_batches.json` 相互独立 → **N 个账户都认为该批次未处理，各下 N 笔真单**
3. N 个客户端 POST 回同一 `batch_id` → 服务端幂等检查使第 2~N 次直接返回
   `note: idempotent` 且**不写结果文件**
4. 客户端收到 `{"status": "ok"}`，**视为成功**

**净效果：N 个账户真实成交，策略端只记录到 1 笔，其余 N-1 笔的成交、持仓与结果永久丢失。**
该过程**无任何报错或告警**。

> 单账户使用时不存在此问题（服务端 `processed` 与本地账本一一对应）。
> **引入多账户前必须先解决。**

## 改进方向（尚未实施）

按优先级记录，暂未排期：

1. **多用户隔离**（优先）— 服务端按 `user` 切分命名空间（`~/trade/userN/`），
   `decisions` 缓存键改为 `(user, for_date)`，`batch_id` 按 `(user, for_date)` 生成，
   `processed` 与 results 按用户落盘。
   *决策内容可共享（同一策略同一信号），必须隔离的是执行态* —— 同一信号在两个账户上是
   两笔不同成交，共用 `batch_id` 会让后者被幂等检查吃掉。
2. **应用层鉴权** — 客户端新增 `GM_TRADE_TOKEN` / `GM_TRADE_USER`，经
   `X-Trade-Token` / `X-Trade-User` 头下发；服务端按用户校验并记录审计日志。
   校验方式可复用本仓 `dashboard/trade_server.py` 已有的 `secrets.token_hex(16)` +
   `secrets.compare_digest` 范式。
3. **证书校验** — 将 nginx 自签证书随安装包分发，`GM_SSL_VERIFY` 指向该文件。
   必须先于第 2 项落地，否则令牌可被窃取。
4. **nginx 层** — 为 `/trade/` 增加 `auth_basic`（使用**独立** htpasswd，
   不复用 dashboard 凭据，避免看板用户自动获得交易写权限）与 `limit_req`。
   出口 IP 动态，**不建议**用 IP 白名单。

> 上线顺序须**先客户端、后服务端**：客户端改动保持向后兼容（配置了令牌才发送），
> 全部升级完成后再开启服务端强制校验，否则会造成多个客户端同时断线。
> 本仓已有自动更新通道（`updater.py` + `version.json` + GitHub Releases）可用于分发。
