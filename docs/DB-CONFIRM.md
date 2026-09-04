# 双端联调前：DB 端需确认清单（交易端 LKL-Trade）

主契约见 `docs/exchange-contract.v2.md`。以下是我方已按 v2 实现、但含**交易端假设**、
必须 DB 端拍板的点。**#1(window 语义)、#4(decisions 生命周期) 与 #10(回报 status 语义) 已拍板 ✅（见下表）；
其余为语义澄清建议，非阻塞。**

| # | 点 | 交易端现状 | 需 DB 确认 |
|---|---|---|---|
| 1 | **window 执行语义（v2）** ✅ | **已拍板（v2 起）：window 仅为展示标签，不参与执行判断**；执行唯一依据 `exec`（OPEN_POS↔BUY / CLOSE_ALL↔SELL，缺失按 action 兜底）。SELL 清仓与 window=NONE 并存是正常组合，照样下单（回归测试 `test_close_all_season_sell_executes`）；不再产生 EXCLUDED | DB 生成端无需管 window 取值：开仓发 `BUY+OPEN_POS`、清仓发 `SELL+CLOSE_ALL`；window 随意（MORNING/AFTERNOON/NONE…），交易端不据此拦单 |
| 2 | results 行字段 | 消费字段 `action/code/ok/price/shares/order_id/reason`；另带 `status/status_label/note/traded_at/confirmed/ref` | 附加字段 DB 忽略即可？`reason` 空时我方回填决策原因（兼容 SELL 成功“断板卖出”）可否接受 |
| 3 | SELL 未成交 | `ok:false`，保留自动重试（当日 ≤3 次），recon 标“待处理” | DB 语义=保持持仓 OPEN、**次日发新 for_date** 重试？（勿重发同日——我方 ref 含日期） |
| 4 | decisions 删/保留归属 ✅ | **已拍板：先归档本地 `archive/<日期>/` → 再删远端**（`for_date==day` 守卫防误删新一天投递；`GM_KEEP_REMOTE=1` 才保留远端，作审计追溯） | DB 侧**只投递、不删不标记**；远端 decisions 生命周期归交易端。建议 DB 消费依据用 `results/holdings`（带 `ref`）；若仍直接消费 decisions，请按 `for_date|code|action` 幂等（同一文件重复读无副作用，删的是远端副本） |
| 5 | 空执行回执 | 有 decisions 文件必写 results（含 `trades:[]`）；无文件不写 | 以“收到 results”判定交易端已处理，是否与我方一致 |
| 6 | holdings 字段 | `price`(=last_price) 新增，保留 `vwap/last_price`；code 无前缀、symbol 带前缀 | DB 用 price 还是 vwap？全量 DELETE+重建语义按你方文档 |
| 7 | 多用户归属 | results/holdings 写各自 user1/user2 目录，行内无 account | DB 按目录区分账户即可？还是需要文件/行内带 account_id |
| 8 | 文件名/时区 | 秒级 `YYYYMMDD_HHMMSS.json` + Asia/Shanghai(+8) | 确认服务器侧按 +8 判读、不按 UTC 错日 |
| 9 | 拒单重试上限 | 当日 3 次后停止自动，留待人工（`lkl trade resolve`） | DB 的“T+1 重试”靠次日 decisions 实现？当日 ≤3 次窗口内 DB 无需介入？ |
| 10 | **回报 status 语义（v2）** ✅ | results 行自带显式 `status`；消费端**优先取显式值**，禁止用 reason 含字启发式猜状态（仅 schema1 旧格式回落 reason 启发式）。三态口径：`REJECTED`=门禁/券商拒（**可重试**，非终态，留档待开市/次日再试，仓位不动）；`CANCELLED`=撤单（终态）；`EXCLUDED`=决策排除（历史/人工，v2 起不再产生） | **已拍板（2026-09-04 联调）**：DB `sell_fail` 改为显式 status 优先（`lkl/trade/apply.py`，commit `afa0868`，测试 `test_sell_rejected_explicit_status_wins`）。trade_event 只存 CANCELLED/REJECTED 两态，**不新增独立 EXCLUDED 存储态**——历史 4 份 EXCLUDED 当时按 reason 回落记为 REJECTED，v2 起不再产生，加第三态收益为 0 不动 schema/面板/测试 |

## 联调验收口径（第 8 节）

- 仿真环境连续运行多个交易日；验收标准：每条决策 ↔ 最终委托 ↔ 成交 ↔ 持仓一一核对
  （交易端 `lkl trade recon` 全绿；DB 侧合并对账一致）。
- 未清零前不启用开机自启与无人值守自动委托；可继续账户查询/持仓同步/只读看板。