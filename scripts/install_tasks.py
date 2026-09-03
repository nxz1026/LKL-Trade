import os, subprocess, sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_PY = _REPO / ".venv-trade" / "Scripts" / "python.exe"
_PY = _PY if _PY.exists() else Path(sys.executable)
_GOLD = os.environ.get("GOLDMINER_EXE",
                       r"C:\Users\ND\AppData\Roaming\Hongshu Goldminer3\goldminer3.exe")
_TASKS = {"LKLGoldminer": (_GOLD, "", 0),
          "LKLTradeSup": (_PY, "-m lkl.main sup", 1),
          "LKLDash": (_PY, "-m lkl.main dash", 0)}
def _ps(sc: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", sc], capture_output=True)
    out = r.stdout.decode("utf-8", "replace") or r.stdout.decode("gbk", "replace")
    if r.returncode:
        raise SystemExit(f"[ps失败] {out}")
    return out


def install() -> int:
    lines = []
    for name, (exe, arg, rk) in _TASKS.items():
        delay = ';$t.Delay="PT1M"' if rk else ""
        st = "New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Seconds 60)" if rk else "Null"
        lines += [f"$t=New-ScheduledTaskTrigger -AtLogOn{delay};",
                  f"$a=New-ScheduledTaskAction -Execute \"{exe}\" -Argument \"{arg}\" -WorkingDirectory \"{_REPO}\";",
                  f"$s={st};Register-ScheduledTask -TaskName '{name}' -Action $a -Trigger $t -Settings $s -Force -ErrorAction Stop;"]
    try:
        _ps("".join(lines))
    except SystemExit as e:
        if "denied" in str(e).lower() or "0x80070005" in str(e):
            print("需以管理员(右键)运行本脚本")
        raise
    return 0


def uninstall() -> int:
    _ps("Unregister-ScheduledTask -TaskName LKLGoldminer,LKLTradeSup,LKLDash -Confirm:$false -ErrorAction SilentlyContinue")
    print("已卸载")
    return 0


def status() -> int:
    print(_ps("Get-ScheduledTask | ? {$_.TaskName -match 'LKL'} | ft TaskName,State -Auto"))
    return 0


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "install"
    {"install": install, "uninstall": uninstall, "status": status}[a]()