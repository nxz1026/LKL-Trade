# Trade HTTP API 协议

> LKL-Trade v2.1+ — 决策/结果 HTTP 交换协议

## 概述

HTTP 模式通过 Oracle 端的 `trade_api.py` Flask 服务实现决策拉取和结果回传，
替代原有的 SFTP 文件传输方式。holdings 和 manual_orders 仍通过 SFTP 传输。

## 启用方式

客户端 `config.env` 设置：

```
GM_REMOTE_URL=https://140.83.62.161/trade
GM_SSL_VERIFY=false
```

设置后 `process_once()` 自动走 HTTP 模式；未设置时回退 SFTP 模式。

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
      "reason": "ma_golden_cross score=78"
    }
  ]
}
```

**响应 204：** 当日无决策

- `batch_id` 是全局唯一标识（UUID），客户端用于幂等追踪
- 同日期多次拉取返回相同 `batch_id`（决策未刷新时）
- 决策刷新后生成新 `batch_id`

### POST /results

回传执行结果。

**请求体：**
```json
{
  "for_date": "2026-09-30",
  "trades": [
    {
      "action": "BUY",
      "code": "000504",
      "ok": false,
      "price": 0,
      "shares": 0,
      "order_id": "",
      "reason": "非交易日或不在盘中时段，暂停自动下单"
    }
  ]
}
```

**响应 200：**
```json
{
  "ok": true,
  "written": "results_2026-09-30_20260930_131428.json"
}
```

**响应 400：** 请求体格式错误

- 结果写入 Oracle `~/trade/results_{date}_{timestamp}.json`
- 对应 `batch_id` 标记为已处理（幂等）
- 重复 POST 同一 `batch_id` 返回 `{"ok": true, "duplicate": true}`

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

**响应 404：** 当日无结果

### GET /health

健康检查。

**响应 200：**
```json
{"ok": true, "service": "trade_api"}
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
| 200 | 成功 | 正常处理 |
| 204 | 无决策 | 跳过，等待下次轮询 |
| 400 | 请求格式错误 | 告警，不重试 |
| 404 | 无结果 | 跳过 |
| 500 | 服务端错误 | 告警，下次轮询重试 |
| 网络不可达 | 连接失败 | 告警，回退等待 |

## nginx 配置（Oracle 端）

```nginx
location /trade/ {
    proxy_pass http://127.0.0.1:8032/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 30s;
}
```

客户端访问 `https://140.83.62.161/trade/decisions?date=...`
等价于 `http://127.0.0.1:8032/decisions?date=...`。

## 安全

- HTTPS 加密传输（nginx SSL 终端）
- 自签证书场景客户端设置 `GM_SSL_VERIFY=false`
- 服务端绑定 127.0.0.1，仅 nginx 反代暴露
- 无认证头（内网/VPN 场景），如需认证可加 `X-Bridge-Token`
