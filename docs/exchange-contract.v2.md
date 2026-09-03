# v2 交换契约（DB/策略端 ↔ 交易端 LKL-Trade）

> 供DB侧与交易侧对齐。DB 消费字段以「DB 消费」标注；其余为本交易端看板/审计保留字段，
> DB 可忽略不处理（多写无害，增删也兼容）。
> 文件名一律 `{kind}_YYYYMMDD_HHMMSS.json`，时间戳 **Asia/Shanghai(+8)**，秒级。

## 1. decisions（DB → 交易端，只读后自删）

```json
{ "schema": 1, "for_date": "2026-09-03", "generated_at": "…+08:00",
  "actions": [ {"action": "SELL", "code": "601988", "reason": "退潮期清仓建议",
                "volume": 100, "window": "NONE"} ] }
```
- `code` 6位无前缀；`action ∈ BUY|SELL`；`volume`：BUY=0 / SELL=建议股数。
- `window`：`""`/`ANY`/`DAY` 放行；`MORNING`/`AFTERNOON` 仅对应时段放行；
  `NONE` 或未识别 → **EXCLUDED 不进单**（交易端明确不触发订货）。
- 交易端读取（文件名倒序取当 for_date 最新）→ 执行 → **自删该 decisions 文件**。

## 2. results（交易端 → DB，每次执行写新时间戳文件）

```json
{ "schema": 1, "for_date": "2026-09-03", "trades": [ … ] }
```

每份 trades[] 行（**DB 消费字段**）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `action` | str | BUY / SELL |
| `code` | str | 6 位，无前缀 |
| `ok` | bool | **已成交**（不是 order_id 存在） |
| `price` | number | 成交均价 |
| `shares` | number | 成交数量（SELL 无则 0） |
| `order_id` | str | 券商委托号（未成可为空） |
| `reason` | str | 失败/拒因；无则取决策原因（兼容 SELL 成功 `"断板卖出"`） |

**DB 忽略的保留字段**（交易端额外给，看板/审计用，不影响消费）：
`ref`(幂等键), `status`/`status_label`/`confirmed`, `filled`, `remaining`,
`avg_price`, `note`(决策原因), `traded_at`。

> 对齐确认点：交易端**同时输出 `status` 字段**；`reason` 与 `note` 两个都存在——
`note`=决策原因、`reason`=失败/拒因(空则回填决策原因)。DB 若要「成交后对账」建议消费
`ok/price/shares` 即可，不需要看 status。

## 3. holdings（交易端 → DB，全量快照）

```json
{ "schema": 1, "for_date": "2026-09-03", "account": "…",
  "holdings": [ {"code": "601988", "symbol": "SHSE.601988",
                 "volume": 100, "available": 100, "cost": 6.7,
                 "price": 6.7, "fpnl": 0.0} ] }
```

- DB 语义：DELETE 全部 OPEN 后按快照重建；空 holdings = 0 持仓（真清仓也照写）。
- `code` 无前缀；`symbol` 带前缀；`price`=`last_price` 最新参考价（兼容旧 `vwap`）。
- 保留字段：`vwap`, `last_price`。

## 6. 幂等与归档

- 交易端「写完 results/holdings 新文件即可」，db 侧归档移走；不做重复写。
- 交易端唯一主动 `rm` 的是自己已执行的 decisions（`GM_KEEP_REMOTE=1` 时保留供对账追溯）。
- 本地衍生文件（交易端自己维护、**不进 v2 契约、不上传远端**）：`executed.json`(防重账本)、
  `pending.json`(下单意图)、`governance.json`(演练/实盘/急停)、`resolved.json`(人工处置留痕)、
  `heartbeat.json`(本地进程脉冲)、`alerts.jsonl`(分级告警)。跨机存活证据=results/holdings 文件本身。

## 与旧版差异（DB 需知）

- 原名 `vwap/last_price` → 新增 `price`。
- results 行新增 `price`/`shares`/`ok`（原名 ok=confirmed 变名 ok）。
- 文件名无毫秒后缀（秒级）。
- 传输改为**受限 SFTP**（无 shell），各用户目录 `trade/userN/` 隔离。
- `status` 字段新增并在看板使用，DB 侧不需要，忽略即可。