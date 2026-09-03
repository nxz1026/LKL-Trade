"""远端交换目录同步：受限 SFTP（v2 契约）。

- 只用 `sftp` 协议：无 shell、无端口转发，不允许 ``ssh ... sh -c``。
- 每个用户只操作自己的子目录；``GM_REMOTE_DIR`` = 登录落点(交换根)下的用户子目录
  （如 ``user1``）。任何绝对路径或含 ``..`` 的路径直接拒绝，防越界。
- 文件身份一律**文件名**（basename）；`ls`/`get`/`put`/`rm` 均在目标目录内完成，
  失败抛 `RemoteError` 上抛阻断。

不配置 ``GM_REMOTE_HOST`` 则纯本地（enabled()=False，各操作 no-op）。
"""
from __future__ import annotations
import re
import subprocess

from lkl.broker import config, fileio

_FNAME = re.compile(r"^(?P<kind>[a-z]+)_(?P<ts>\d{8}_\d{6})\.json$")


class RemoteError(RuntimeError):
    """远端同步失败——必须显式冒泡阻断，不静默当成功。"""


def enabled() -> bool:
    return bool(config.remote_host())


def _sftp(script: str) -> str:
    cmd = ["sftp", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
           "-o", "ConnectTimeout=10", "-i", str(config.remote_key()),
           config.remote_host()]
    r = subprocess.run(cmd, input=script, text=True, capture_output=True)
    if r.returncode != 0:
        raise RemoteError(f"sftp 失败 rc={r.returncode}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def _cd() -> str:
    """进入用户子目录；绝对路径 / 含 .. 一律拒绝防越界到他人目录/根。"""
    raw = (config.remote_dir() or "").strip()
    if not raw:
        return ""
    d = raw.strip("/")
    if raw.startswith("/") or d in (".", "..") or ".." in d.split("/"):
        raise RemoteError(f"非法远端目录访问被拒绝: {raw!r}")
    return f"cd {d}\n"


def _names(kind: str) -> list:
    """远端目录内该 kind 全部时间戳文件名（升序）。"""
    out = _sftp(_cd() + f"ls -1 {kind}_*.json\n")
    names = []
    for line in out.splitlines():
        m = _FNAME.match(line.strip())
        if m and m.group("kind") == kind:
            names.append(line.strip())
    return sorted(set(names))


def newest(kind: str) -> str:
    """远端最新 {kind}_*.json 文件名；无则空串。"""
    if not enabled():
        return ""
    ns = _names(kind)
    return ns[-1] if ns else ""


def rm(name: str) -> None:
    if enabled() and name:
        _sftp(_cd() + f"rm {name}\n")


def pull(kind: str) -> None:
    """把远端最新 {kind} 拉到本地；失败抛 RemoteError。"""
    if not enabled():
        return
    name = newest(kind)
    if not name:
        return
    _sftp(_cd() + f"get {name} {fileio.directory() / name}\n")


def push(kind: str) -> None:
    """把本地最新 {kind} 推到远端用户目录；失败抛 RemoteError。"""
    if not enabled():
        return
    p = fileio.latest(kind)
    if not p:
        return
    _sftp(_cd() + f"put {p} {p.name}\n")