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
_PYW = Path(str(_PY).replace("python.exe", "pythonw.exe"))
_PYW = _PYW if _PYW.exists() else _PY


def _base_pythonw() -> Path:
    """venv Scripts/pythonw.exe 是 uv launcher stub：任务直启它会驻留 stub 再派生 base
    python.exe(console)，开机即多一个黑框。改从 pyvenv.cfg home 解析 base 目录的真
    pythonw（无 stub、无 console、单进程）。托盘本体只 import 标准库，无需 venv 上下文；
    服务的 venv 环境由 lkl_tray.py 内部经 venv stub(CREATE_NO_WINDOW) 保证。"""
    try:
        cfg = (_REPO / ".venv-trade" / "pyvenv.cfg").read_text(encoding="utf-8")
        for line in cfg.splitlines():
            if line.startswith("home = "):
                pw = Path(line[len("home = "):].strip()) / "pythonw.exe"
                if pw.exists():
                    return pw
    except OSError:
        pass
    return _PYW  # 兜底(venv stub)
_GOLD = _find_gold()

# 托盘(LKLTray, base 真 pythonw 无黑框) 托管 sup+dash；不再分别注册 console 任务
_TASKS = {"LKLGoldminer": (_GOLD, "", False),
          "LKLTray": (_base_pythonw(), "scripts/lkl_tray.py", True)}
_LEGACY = ("LKLTradeSup", "LKLDash")   # 旧任务：卸载时一并清理


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
    if not _PYW.exists():
        bad.append(f"pythonw 缺失: {_PYW}（托盘需无窗口启动）")
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
        trigger = f"$t=New-ScheduledTaskTrigger -AtLogOn{delay}"
        arg_clause = f' -Argument "{arg}"' if arg else ""   # 空参数必须省略（验证不允许空串）
        action = f'$a=New-ScheduledTaskAction -Execute "{exe}"{arg_clause} -WorkingDirectory "{_REPO}"'
        # 只有重启任务传 -Settings（$null 会触发 Register 参数校验错）
        if restart:
            st = ("$s=New-ScheduledTaskSettingsSet -RestartCount 3 "
                  "-RestartInterval (New-TimeSpan -Seconds 60);")
            settings = " -Settings $s"
        else:
            st, settings = "", ""
        cmd = (f"{trigger};{action};{st}"
               f"Register-ScheduledTask -TaskName '{name}' -Action $a -Trigger $t"
               f"{settings} -Force -ErrorAction Stop;")
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
    """幂等卸载：只删现存任务；一个都没有也算成功（不再对不存在任务抛错）。"""
    names = ", ".join(f"'{n}'" for n in list(_TASKS) + list(_LEGACY))
    out = _ps(
        "$ErrorActionPreference='SilentlyContinue';"
        f"$all=Get-ScheduledTask; $hit=$all | ? {{ $_.TaskName -in @({names}) }};"
        "if($hit){ $hit | ForEach-Object { Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false } }"
        "; Write-Output ('removed=' + @($hit).Count)")
    print(f"已卸载（移除 {out.split('removed=')[-1].strip()} 个现存任务；无任务则跳过）")
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