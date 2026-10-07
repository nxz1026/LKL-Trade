"""全套测试的**全局隔离兜底**：绝不触达真实上游。

## 为什么需要这个文件（2026-10-07）

各测试文件自己的 `env` fixture 都在做同一件事——把交换目录指到 tmp_path、
关掉远端。但它们只关掉了 **SFTP** 的 `config.remote_host` / `remote_dir`，
**漏了 HTTP 的 `config.remote_url`**。

后果：在**配了 `GM_REMOTE_URL` 的机器上**（也就是交易机自己，本机的
`config.env` 里就有），`process_once()` 里的
`if config.remote_url(): return _process_once_http(...)` 会命中，整套路法
**真的连上生产 oracle**。实测跑一次就在生产侧打出
`InsecureRequestWarning: Unverified HTTPS request is being made to host '140.83.62.161'`。

当时**侥幸**没有造成污染：上游当日 `actions` 为空，`_process_once_http`
在 `if not actions: return 0` 就返回了，什么都没写。但这是运气不是设计——
一旦在**上游有信号的日子**跑测试，`exchange.dump_results` 与
`http_push_results` 会把**假的 results POST 回生产**的 `/home/ubuntu/trade`，
污染生产的 `state.json` 与情绪核的防重账本；而 `env` fixture 里
`governor.set_mode("armed", "test")` 又把治理门禁打开了。

## 做法

autouse fixture，全局生效（连没有 `env` fixture 的用例也覆盖），把三种远端
访问方式**一起**清空。想测 HTTP 模式的用例，用例内部自己
`monkeypatch.setattr(config, "remote_url", lambda: "...")` 覆盖即可。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_live_remote(monkeypatch):
    """清空 SFTP + HTTP 全部远端出口——测试必须是 hermetic 的。"""
    from lkl.broker import config

    monkeypatch.setattr(config, "remote_host", lambda: "")
    monkeypatch.setattr(config, "remote_dir", lambda: "")
    monkeypatch.setattr(config, "remote_url", lambda: "")