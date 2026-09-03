"""注册/卸载 Windows 计划任务：金矿终端自启 + LKL-Trade 调度器自启。

用法: python scripts/install_tasks.py [install|uninstall|status]
env:  GOLDMINER_EXE 覆盖终端路径。需管理员权限注册（拒绝访问时提示）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = REPO / ".venv-trade" / "Scripts" / "python.exe"
PY = PY if PY.exists() else Path(sys.executable)
GOLD = os.environ.get("GOLDMINER_EXE",
                      r"C:\Users\ND\AppData\Roaming\Hongshu Goldminer3\goldminer3.exe")


def _ps(script: str, admin: bool = False) -> str:
    args = ["powershell", "-NoProfile", "-Command", script]
    if admin:
        args = ["powershell", "-NoProfile", "-Command",
                f"Start-Process powershell -Verb RunAs -Wait -ArgumentList "
                f"'-NoProfile -Command \"{script}\"'"]
    r = subprocess.run(args, capture_output=True)
    out = _dec(r.stdout); err = _dec(r.stderr)
    if r.returncode != 0:
        raise SystemExit(f"[ps失败] {err or out}")
    return out


def _dec(b: bytes) -> str:
    return b.decode("utf-8", "replace") or b.decode("gbk", "replace")


def _script() -> str:
    return rf"""
$g='{GOLD}'; $py='{PY}'; $repo='{REPO}'
function NewTask($name,$exe,$arg,$delay,$rc){{
  $t=New-ScheduledTaskTrigger -AtLogOn; if($delay){{$t.Delay=$delay}}
  $a=New-ScheduledTaskAction -Execute $exe -Argument $arg -WorkingDirectory $repo
  $s=$null; if($rc){{$s=New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Seconds 60)}}
  Register-ScheduledTask -TaskName $name -Action $a -Trigger $t -Settings $s -Force -ErrorAction Stop
}}
NewTask 'LKLGoldminer' $g '' $null $false
NewTask 'LKLTradeSup' $py '-m lkl.main sup' 'PT1M' $true
'OK'"""


def install() -> None:
    try:
        _ps(_script())
    except SystemExit as e:
        if any(k in str(e).lower() for k in ("0x80070005", "access", "denied", "拒绝")):
            print("注册需要管理员权限（UAC）。请以管理员运行：")
            print(f"  python \"{REPO/Path('scripts/install_tasks.py')}\" install")
        raise
    print("已注册：LKLGoldminer + LKLTradeSup（自启）")


def uninstall() -> None:
    _ps("Unregister-ScheduledTask -TaskName LKLGoldminer,LKLTradeSup -Confirm:$false -ErrorAction SilentlyContinue")
    print("已卸载")


def status() -> None:
    print(_ps("Get-ScheduledTask | Where-Object {$_.TaskName -match 'LKL'} | "
              "Format-Table -Auto TaskName,State"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["install", "uninstall", "status"], nargs="?", default="install")
    a = ap.parse_args()
    {"install": install, "uninstall": uninstall, "status": status}[a.action]()