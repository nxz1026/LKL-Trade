# LKL-Trade 交易端测试步骤

分级测试：①隔离单元/故障注入 → ②只读/回写 → ③仿真单笔执行 → ④常驻多日。全部通过才谈无人值守。

## 前置（你的机器）

```bash
cd E:/2026Workplace/Code/LKL-Trade
# 1) 金矿终端(Hongshu Goldminer3) 启动并登录模拟账户，127.0.0.1:7001 可达
# 2) 使用 cp310 环境（gmtrade 依赖）
E:/2026Workplace/Code/LKL-Trade/.venv-trade/Scripts/python.exe -m lkl.main doctor
#    期望：除「决策样例」外全部 ✓（该项可等 DB 投递）
# 3) SFTP 通（受限 v2）
sftp -i ~/.ssh/DJ.pem ubuntu@ec2-35-78-74-90.ap-northeast-1.compute.amazonaws.com
> cd DSH/longkonglong/trade/user1 && ls     # 能看到 consumed/ 即通
```

## ① 单元/故障注入（无终端、无 DB、无远端）

```bash
python -m pytest tests/ -v        # 期望 37 passed
python -m lkl.main trade govern status   # 默认 dry · 绑定账户 - · 在途 0
```

覆盖：拒单不入账本 / 崩溃在途不重下 / 并发单执行器锁 / 部分成交不重复下单 /
SELL+window=NONE 照常下单（v2 展示标签）/ 坏决策文件整批拒绝 / 账本损坏阻断 /
对账一致与冲突 / 人工处置 ignore|complete / 周末不开市 / v2 结果行字段。全绿再往下。

## ② 只读与回写（需终端；远端仍隔离）

```bash
lkl sim                    # 账户/资金/持仓正常
lkl sim sync               # holdings 快照 → 本地 + user1/
```

> 若 DB 正在轮询，results/holdings 会在一分钟内被它归档走。想隔离观察：请 DB 停
> 30 分钟，或只看本地 `~/trade/user1/`。

## ③ 仿真单笔执行（模拟账户=仿真资金）

```bash
lkl trade govern arm       # doctor 关键项过才放行
# 投放 decisions_YYYYMMDD_*.json 到 user1（含 1 BUY 601988）
lkl trade preview          # 交易日/账户/拟量/占用/阻断原因
lkl trade                  # 单次执行
lkl trade recon            # 期望 一致 1 / 异常 0
lkl trade alerts           # 无 CRIT
lkl dash                   # 浏览器 http://127.0.0.1:8200：治理=实盘、对账、告警
```

核对：`results_*.json` 字段含 ok/price/shares/order_id/status/status_label/reason；
`executed.json` 只记成交 ref；user1 中 decisions 已自删。

急停验证：

```bash
lkl trade govern halt      # 输出若含「在途 X 笔」；持久（重启仍停）
lkl trade govern resume; lkl trade govern dry
```

## ④ 常驻 / 多交易日（最后一步）

```bash
lkl sup 60                 # 跑一个交易时段；heartbeat.json 每 ≤60s 更新 last_success
```

**验收门槛不是“程序没报错”**：每一条决策都能与委托/成交/持仓一一对上（recon 全绿）；
跨日后再对昨日仍一致。P0/P1 未清零、双端未联调通过前，**不启用 Windows 开机自启**。