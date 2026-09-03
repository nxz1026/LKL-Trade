"""lkl sim CLI 分发：info 账户 / order 下单 / orders 委托 / sync 持仓快照。"""
from __future__ import annotations

from lkl.broker import config, reachability


def _precheck() -> int | None:
    """凭据/端点预检；不满足返回退出码提示。"""
    if not config.token() or not config.account_id():
        print("未配置凭据：写入 .secrets/gm.env 或设 GM_TOKEN/GM_ACCOUNT_ID")
        return 2
    if not reachability.endpoint_reachable(config.endpoint()):
        print(f"⚠ 端点 {config.endpoint()} 不可达：请启动金矿终端并连接账户")
        return 3
    return None


def _info() -> None:
    from lkl.broker.info import user_info
    from lkl.broker.render import render_user
    print(render_user(user_info()))


def run(argv: list[str]) -> int:
    """lkl sim 分发：info(默认)/order/orders/sync。"""
    err = _precheck()
    if err:
        return err
    try:
        action = argv[0] if argv else "info"
        if action == "order":
            from lkl.broker.commands import do_order
            do_order(argv[1:])
        elif action == "orders":
            from lkl.broker.commands import list_orders
            list_orders()
        elif action == "sync":
            from lkl.broker import holdings, sync
            n = sync.snapshot()
            print(f"holdings 快照 {n} 条 -> {holdings.path()}")
        else:
            _info()
    except (ConnectionError, RuntimeError) as e:
        print(f"{type(e).__name__}: {e}")
        return 1
    return 0