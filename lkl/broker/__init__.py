"""掘金仿真交易桥接（P4 with-trade）：连接本地金矿终端，模拟盘查询与下单。

gmtrade 仅 cp310 可用 -> 本包在 .venv-trade（Python 3.10）下运行。
init 保持零导入（不引 gmtrade），避免主 venv 无关命令被拖连；各子模块按需单独导入。
"""