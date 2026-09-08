"""配置唯一出口：env 优先、回退 .secrets/gm.env；禁散落 os.environ。

交易：GM_TOKEN/GM_ACCOUNT_ID/GM_ENDPOINT/GM_ENV_FILE/TRADE_DIR
时段：GM_HOLIDAYS(休市日补充)
风控：GM_RISK_MAX_QTY/GM_RISK_MAX_ORDERS/GM_RISK_MAX_CODES
对账/追溯：GM_RECON_ORDERS(对账联券商委托)、GM_KEEP_REMOTE(1=归档后保留远端决策供审计)
远端：GM_REMOTE_HOST/GM_REMOTE_KEY/GM_REMOTE_DIR(受限SFTP用户子目录)
更新：GM_UPDATE_URL(version.json 目录) / GM_UPDATE_INTERVAL_HOURS(自动检查间隔,0=关) /
      GM_UPDATE_AUTO(1=发现新版自动静默更新)
模板见 .env.example，取值见 README。"""
from __future__ import annotations
import os
import sys
from pathlib import Path

from lkl.broker.version import __version__ as APP_VERSION

_DEFAULTS = {"GM_ENDPOINT": "127.0.0.1:7001", "TRADE_DIR": "~/trade",
             "GM_UPDATE_INTERVAL_HOURS": "6"}
_REPO = Path(__file__).resolve().parents[2]


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """应用目录：源码=仓库根；frozen(打包)=可执行文件所在目录（安装目录）。"""
    if _frozen():
        return Path(sys.executable).resolve().parent
    return _REPO


def config_dir() -> Path:
    """配置目录：frozen=应用目录（config.env 随安装位置，卸载即清）；源码=<仓库根>。"""
    return app_root()


def _env(key: str) -> str:
    return os.environ.get(key) or _DEFAULTS.get(key, "")


def secrets_file() -> Path:
    return Path(_env("GM_ENV_FILE") or str(app_root() / "config.env")).expanduser()


def _secret(name: str) -> str:
    """从环境变量或 .secrets/gm.env 读取。

    解析规则：支持 export 前缀、`KEY = v` 空格、行内 ` # 注释`、引号包裹的值；
    值内含 `=` 原样保留（partition 取首个 = 之后全部）。
    """
    if os.environ.get(name):
        return os.environ[name]
    f = secrets_file()
    if not f.exists():
        return ""
    for line in f.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[len("export "):].strip()
        key, sep, val = s.partition("=")
        if not sep or key.strip() != name:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            return val[1:-1]      # 引号包裹：整段取值，含 # 也保留
        if " #" in val:
            val = val.split(" #", 1)[0].rstrip()   # 行内注释（空格+井号）
        return val
    return ""


def token() -> str:
    return _secret("GM_TOKEN")


def account_id() -> str:
    return _secret("GM_ACCOUNT_ID")


def endpoint() -> str:
    return _env("GM_ENDPOINT")


def trade_dir() -> Path:
    return Path(_env("TRADE_DIR")).expanduser()


def remote_host() -> str:
    return _secret("GM_REMOTE_HOST")


def remote_key() -> Path:
    return Path(_secret("GM_REMOTE_KEY")).expanduser()


def remote_dir() -> str:
    return _secret("GM_REMOTE_DIR")


def holidays() -> tuple:
    """休市日集合（YYYY-MM-DD 逗号分隔，中英文逗号均可），来自 GM_HOLIDAYS 或 .secrets/gm.env。"""
    raw = _secret("GM_HOLIDAYS").replace("，", ",")
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def update_url() -> str:
    """自动更新源：version.json 所在目录（http(s):// 或 file:// 本地测试用）。空=不检查。"""
    return _secret("GM_UPDATE_URL")


def update_interval_hours() -> int:
    """自动检查更新间隔（小时）；0=关闭自动检查（仅菜单手动触发）。"""
    raw = _secret("GM_UPDATE_INTERVAL_HOURS")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 6


def update_auto() -> bool:
    """1=发现新版自动静默更新（交易时段自动延后）；0=仅气泡提示、菜单手动更新。"""
    return _secret("GM_UPDATE_AUTO").strip() == "1"


_RISK_KEYS = (("GM_RISK_MAX_QTY", "max_qty"),
              ("GM_RISK_MAX_ORDERS", "max_orders"),
              ("GM_RISK_MAX_CODES", "max_codes"))


def risk_limits() -> dict:
    """风控护栏上限（0=不限制，无法表达「最多 0 单」，留空即不限）：
    GM_RISK_MAX_QTY 单笔最大股数 / GM_RISK_MAX_ORDERS 当日最大下单次数 /
    GM_RISK_MAX_CODES 当日最多操作只数。

    读取走 _secret（env 优先、回退 .secrets/gm.env）：看板 set_risk_limits 写盘
    gm.env 后即刻生效，无需重启/热更进程环境。
    """
    out = {}
    for key, name in _RISK_KEYS:
        raw = _secret(key).strip()
        try:
            out[name] = int(raw) if raw else 0
        except ValueError:
            out[name] = 0
    return out


def set_risk_limits(values: dict) -> dict:
    """看板可视化修改风控上限 → 写入 .secrets/gm.env（覆盖/追加键）。

    仅接受 _RISK_KEYS 内的键，值为非负整数；写入失败（secrets 文件不可写）
    抛 OSError，由调用方（HTTP 层）转 500。
    """
    cur = dict(risk_limits())
    for key, name in _RISK_KEYS:
        if name not in values:
            continue
        try:
            v = int(values[name])
        except (TypeError, ValueError):
            raise ValueError(f"{name} 需为整数") from None
        if v < 0:
            raise ValueError(f"{name} 不能为负")
        cur[name] = v
    p = secrets_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    lines = text.splitlines()
    for key, name in _RISK_KEYS:
        newline = f"{key}={cur[name]}"
        found = False
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("export "):
                s = s[len("export "):].strip()
            if s.partition("=")[0].strip() == key:
                lines[i] = newline
                found = True
                break
        if not found:
            lines.append(newline)
    from lkl.broker import fileio
    fileio.atomic_write(p, "\n".join(lines) + "\n")
    return cur


_TEMPLATE = """# LKL-Trade 配置文件（首次运行自动生成，改后需重启 sup/dash 生效）
# 所有键均可改为环境变量（同名覆盖），默认从本文件读取。

# ---------- 掘金仿真凭据（必填） ----------
GM_TOKEN=
GM_ACCOUNT_ID=
# 金矿终端本地服务地址（默认即可，不必设）
GM_ENDPOINT=127.0.0.1:7001

# ---------- 两端共享：JSON 交易通道 ----------
# 交换目录：本机写 results/holdings；策略端写 decisions。
# 默认 %USERPROFILE%\\trade
TRADE_DIR=~/trade

# ---------- 运行依赖 ----------
# 金矿终端(Hongshu Goldminer3) 需在 127.0.0.1:7001 运行且已登录账户
# 契约：decisions.json(策略->本机)、results.json(本机->策略)、holdings.json(真仓快照)
# 休市日补充（逗号分隔 YYYY-MM-DD），周末内置休市
GM_HOLIDAYS=
# 风控护栏（0=不限）：单笔股数 / 当日下单次数 / 当日操作只数
GM_RISK_MAX_QTY=0
GM_RISK_MAX_ORDERS=0
GM_RISK_MAX_CODES=0
# 1=对账联券商当日委托核验
GM_RECON_ORDERS=0
# 1=归档后保留远端决策供审计
GM_KEEP_REMOTE=0
# 告警外部可达通知：逗号分隔 webhook URL（钉钉/企微/Server酱 等 JSON POST 兼容）
GM_ALERT_WEBHOOK=

# ---------- 自动更新 ----------
# 更新源目录：放 version.json + 安装包（任意 http(s) 静态托管/GitHub Release 资产 URL 目录）；
# 空=不检查更新。version.json 结构见 scripts/build_release.py 输出示例。
GM_UPDATE_URL=
# 自动检查间隔（小时，默认 6；0=关闭自动检查，仅托盘菜单手动触发）
GM_UPDATE_INTERVAL_HOURS=6
# 1=发现新版自动静默更新（交易时段自动延后）；0=仅气泡提示、菜单手动更新（默认）
GM_UPDATE_AUTO=0

# ---------- 受限 SFTP 交换（v2，无 shell） ----------
# GM_REMOTE_DIR=你的用户子目录（如 user1）；绝对路径 / 含 .. 会拒绝；不填为纯本地
GM_REMOTE_HOST=
GM_REMOTE_KEY=~/.ssh/DJ.pem
GM_REMOTE_DIR=user1
"""


def ensure_config() -> Path:
    """首启生成 config.env 模板（已存在则跳过）。返回配置文件路径。"""
    p = secrets_file()
    if not p.exists():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_TEMPLATE, encoding="utf-8")
        except OSError:
            pass   # 只读目录等：静默，后续读空值由 doctor 提示
    return p