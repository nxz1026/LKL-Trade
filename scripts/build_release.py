"""发布构建：PyInstaller 打包 → Inno Setup 安装器 → sha256 → version.json。

版本单一来源 lkl/broker/version.py：脚本自动改写 installer.iss 的 MyAppVersion
与本文件同步（手改 version.py 即可发版）。用法（Windows，仓库根）：

    python scripts/build_release.py [--url <下载基础URL>] [--note "<更新说明>"]

--url 给出安装包的完整下载地址（如 https://github.com/you/LKL-Trade/releases/latest/download）
或任意静态托管目录；缺省时 version.json 的 url 填相对文件名（与 version.json 同目录）。

产物：installer/LKL-Trade-Setup-<版本>.exe + installer/version.json。
发布：把这两个文件传到 --url 对应目录即可；GitHub 用户直接传成 Release 资产，
     并在 version.json 里把 url 指向资产直链。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lkl.broker.version import __version__          # noqa: E402

ISS = ROOT / "installer.iss"
DIST = ROOT / "dist" / "lkl_boot"
SPEC = ROOT / "lkl_boot.spec"
PY = ROOT / ".venv-trade" / "Scripts" / "python.exe"


def find_iscc() -> str | None:
    """ISCC.exe：PATH 或常见安装位置。"""
    found = shutil.which("ISCC.exe")
    if found:
        return found
    cands = ["C:/Program Files (x86)/Inno Setup 6/ISCC.exe",
           "C:/Program Files/Inno Setup 6/ISCC.exe"]
    local = os.environ.get("LOCALAPPDATA")   # 用户级安装（Inno 默认勾选"仅当前用户"）
    if local:
        cands.append(str(Path(local) / "Programs" / "Inno Setup 6" / "ISCC.exe"))
    for cand in cands:
        p = Path(cand)
        if p.exists():
            return str(p)
    return None


def sync_iss_version() -> None:
    """installer.iss 的 MyAppVersion 与 version.py 同步。"""
    text = ISS.read_text(encoding="utf-8")
    new, n = re.subn(r'#define MyAppVersion "[^"]+"',
                     f'#define MyAppVersion "{__version__}"', text)
    if n != 1:
        raise SystemExit(f"installer.iss 未找到唯一 MyAppVersion 定义（命中 {n} 处），请检查")
    ISS.write_text(new, encoding="utf-8")
    print(f"installer.iss 版本号已同步为 {__version__}")


def run(cmd: list[str]) -> None:
    print("+", " ".join(str(c) for c in cmd))
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT, env=env)


def main() -> int:
    ap = argparse.ArgumentParser(description="LKL-Trade 发布构建")
    ap.add_argument("--url", default="", help="安装包下载基础 URL（version.json 的 url 前缀）")
    ap.add_argument("--note", default="", help="更新说明（version.json 的 note）")
    args = ap.parse_args()

    py = PY if PY.exists() else shutil.which("python")
    if not py:
        raise SystemExit("未找到打包解释器：.venv-trade/Scripts/python.exe 或 PATH 中的 python")
    iscc = find_iscc()
    if not iscc:
        raise SystemExit("未找到 ISCC.exe：请安装 Inno Setup 6 或把 ISCC.exe 加入 PATH")

    # 1) PyInstaller 打包（onedir）
    run([py, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)])

    # 2) 版本号同步 + Inno Setup 出安装器
    sync_iss_version()
    run([iscc, str(ISS)])

    # 3) sha256 + version.json
    setup = ROOT / "installer" / f"LKL-Trade-Setup-{__version__}.exe"
    if not setup.exists():
        raise SystemExit(f"安装器未生成：{setup}")
    sha = hashlib.sha256(setup.read_bytes()).hexdigest()
    ver = {"version": __version__,
           "url": (args.url.rstrip("/") + "/" if args.url else "") + setup.name,
           "sha256": sha,
           "size_mb": round(setup.stat().st_size / (1024 * 1024), 2)}
    if args.note:
        ver["note"] = args.note
    out = ROOT / "installer" / "version.json"
    out.write_text(__import__("json").dumps(ver, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"version.json 已写入 {out}")
    print(f"安装包：{setup}（{ver['size_mb']} MB，sha256={sha[:16]}…）")
    print("发布：上传安装包与 version.json 到更新源目录（GM_UPDATE_URL 指向该目录即可）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())