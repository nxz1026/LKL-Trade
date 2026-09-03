"""注册/卸载 LKL-Trade 开机自启计划任务（Windows PowerShell）。

整改（对应审计 P2-06）：
- 不再把路径硬编码写死——终端路径可探测/环境变量覆盖，缺文件时报错并给出当前值。
- 非重启任务 settings 用 `$null`（真 PowerShell 空值），不再写裸词 `Null`。
- PowerShell 输出按 utf-8→gbk 依次解码，杜绝 utf8 恒返回字符串导致的解码失效。
- 安装前逐项预检，安装后逐项验收（Get-ScheduledTask 存在性）；任一失败返回非0。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _default_python() -> Path:
    p = _REPO / ".venv-trade" / "Scripts" / "python.exe"
    return p if p.exists() else Path(sys.executable)


def _find_gold() -> str:
    cands = [
        os.environ.get("GOLDMINER_EXE", ""),
        str(Path.home() / "AppData/Roaming/Hongshu Goldminer3/goldminer3.exe"),
        r"C:\Program Files\Hongshu Goldminer3\goldminer3.exe",
        r"C:\Users\ND\AppData\Roaming\Hongshu Goldminer3\goldminer3.exe",
    ]
    for c in cands:
        if c and Path(c).expanduser().exists():
            return str(Path(c).expanduser())
    return cands[1]  # 找不到返回默认，安装前预检查会报缺


_PY = _default_python()
_GOLD = _find_gold()

_TASKS = {"LKLGoldminer": (_GOLD, "", False),
          "LKLTradeSup": (_PY, "-m lkl.main sup", True),
          "LKLDash": (_PY, "-m lkl.main dash", False)}


def _decode(b: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def _ps(script: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", script], capture_output=True, timeout=60)
    out, err = _decode(r.stdout), _decode(r.stderr)
    if r.returncode:
        raise RuntimeError(f"[ps失败 rc={r.returncode}] {err or out}")
    return out


def preflight() -> list[str]:
    """返回所有未就绪项；空=list可安装。"""
    bad = []
    if not _PY.exists():
        bad.append(f"Python 缺失: {_PY}")
    if not Path(_GOLD).exists():
        bad.append(f"金矿终端缺失: {_GOLD}（设 GOLDMINER_EXE 覆盖）")
    return bad


def install() -> int:
    for issue in preflight():
        print(f"  ✗ {issue}")
    if preflight():
        print("安装中止：请先补齐上述缺失")
        return 1
    ok = 0
    for name, (exe, arg, restart) in _TASKS.items():
        delay = ";$t.Delay='PT1M'" if restart else ""
        settings = ("New-ScheduledTaskSettingsSet -RestartCount 3 "
                    "-RestartInterval (New-TimeSpan -Seconds 60)" if restart else "$null")
        trigger = f"$t=New-ScheduledTaskTrigger -AtLogOn{delay}"
        action = f'$a=New-ScheduledTaskAction -Execute "{exe}" -Argument "{arg}" -WorkingDirectory "{_REPO}"'
        cmd = f"{trigger};{action};$s={settings};Register-ScheduledTask -TaskName '{name}' -Action $a -Trigger $t -Settings $s -Force -ErrorAction Stop;"
        try:
            _ps(cmd)
            st = _ps(f"(Get-ScheduledTask -TaskName '{name}').State")
            print(f"  ✓ {name}: {st.strip()}")
            ok += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
    print(f"安装完成 {ok}/{len(_TASKS)} 个")
    return 0 if ok == len(_TASKS) else 1


def uninstall() -> int:
    _ps("Unregister-ScheduledTask -TaskName LKLGoldminer,LKLTradeSup,LKLDash -Confirm:$false -ErrorAction SilentlyContinue")
    print("已卸载")
    return 0


def status() -> int:
    print(_ps("Get-ScheduledTask | ? {$_.TaskName -match 'LKL'} | ft TaskName,State -Auto"))
    return 0


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "install"
    if action == "preflight":
        for issue in preflight() or ["全部路径 OK"]:
            print("  " + issue)
        return 0
    return {"install": install, "uninstall": uninstall,
            "status": status}.get(action, lambda: (print("未知动作") or 1))()


if __name__ == "__main__":
    raise SystemExit(main())