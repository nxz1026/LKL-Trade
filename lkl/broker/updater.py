"""自动更新核心（零第三方依赖，标准库）。

职责：检查远端 version.json → 下载安装包 → 生成 VBS 更新桩（等托盘退出、
静默安装、拉起新托盘）。托盘菜单/定时检查调用；CLI 可经 `lkl_boot update check` 调试。

发布端配套（scripts/build_release.py 生成 version.json）：
    {"version": "1.1.0", "url": "LKL-Trade-Setup-1.1.0.exe", "sha256": "<64hex>"}
url 支持绝对地址或相对 version.json 目录的相对路径。
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_DEFAULT_MAX_BYTES = 100 * 1024 * 1024   # 100MB 安全上限（本包 <20MB，留余量）
_TIMEOUT = 30


class UpdaterError(RuntimeError):
    """更新流程可预期失败（网络/校验/解析），消息直接给用户看。"""


def ver_cmp(a: str, b: str) -> int:
    """语义化版本比较（容忍 v 前缀、任意段数）：a<b → -1，相等 → 0，a>b → 1。

    非纯数字段按字符串比较兜底（如 beta/rc），数字段按数值比较（10 > 9）。
    """
    def _key(v: str):
        out = []
        for seg in v.lower().lstrip("v").split("."):
            base, _, suf = seg.partition("-")
            if base.isdigit():
                if not suf:
                    out.append((0, int(base), 1))          # 正式版：该号段最大
                else:
                    out.append((0, int(base), 0, suf))     # 预发布：< 正式，后缀按字符串序
            else:
                out.append((1, seg))
        return out

    ka, kb = _key(a), _key(b)
    return (ka > kb) - (ka < kb)


def parse_version_json(text: str) -> dict:
    """解析 version.json → {"version", "url", "sha256"?, "note"?}；坏输入抛 ValueError。"""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("version.json 顶层需为对象")
    version = str(data.get("version", "")).strip()
    url = str(data.get("url", "")).strip()
    if not version or not url:
        raise ValueError("version.json 缺 version 或 url 字段")
    out = {"version": version, "url": url}
    if data.get("sha256"):
        out["sha256"] = str(data["sha256"]).strip().lower()
    if data.get("note"):
        out["note"] = str(data["note"]).strip()
    return out


def check(base_url: str, current_version: str,
          timeout: int = _TIMEOUT) -> dict | None:
    """拉取 {base_url}/version.json 比较版本。

    返回 dict（有新版）或 None（已最新）；网络/解析错误抛 UpdaterError。
    """
    base = str(base_url).rstrip("/")
    url = f"{base}/version.json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise UpdaterError(f"更新源不可达：{e.reason or e}") from None
    except OSError as e:
        raise UpdaterError(f"更新源不可达：{e}") from None
    try:
        info = parse_version_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        raise UpdaterError(f"version.json 解析失败：{e}") from None
    if ver_cmp(info["version"], current_version) <= 0:
        return None
    if not urllib.parse.urlparse(info["url"]).scheme:      # 相对路径 → 相对更新源目录
        info["url"] = urllib.parse.urljoin(url, info["url"])
    return info


def download(url: str, dest_dir: Path, sha256: str | None = None,
             max_bytes: int = _DEFAULT_MAX_BYTES,
             timeout: int = _TIMEOUT) -> Path:
    """下载安装包到 dest_dir，流式限大小 + 可选 sha256 校验；失败清理残件。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1] or "setup.exe"
    dest = dest_dir / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp, \
                open(tmp, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UpdaterError(
                        f"安装包超过 {max_bytes // (1024 * 1024)}MB 上限，已中止")
                h.update(chunk)
                f.write(chunk)
    except UpdaterError:
        tmp.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError) as e:
        tmp.unlink(missing_ok=True)
        raise UpdaterError(f"下载失败：{e}") from None
    if sha256 and h.hexdigest() != sha256:
        tmp.unlink(missing_ok=True)
        raise UpdaterError("下载文件校验和不匹配（sha256），已删除，请重试")
    tmp.replace(dest)
    return dest


def _vbs_str(s: str) -> str:
    return s.replace('"', '""')


def write_vbs(setup: Path, tray_pid: int, tray_cmd: str,
              dest_dir: Path | None = None) -> Path:
    """生成 VBS 更新桩：等 tray_pid 退出 → 静默运行安装器（等待）→ 拉起新托盘。

    安装器退出码写 {dest_dir}/last_result.txt，托盘下次启动读取提示失败。
    VBS 由 wscript.exe 运行（无窗口），本进程退出后独立执行——因此本文件必须
    位于安装目录之外（默认 %TEMP%/lkl-update），安装器覆盖安装目录时不受锁。
    """
    dest_dir = Path(dest_dir or (Path(tempfile.gettempdir()) / "lkl-update"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    vbs = dest_dir / "lkl-update.vbs"
    setup_q = _vbs_str(str(setup))
    tray_cmd_q = _vbs_str(tray_cmd)
    result_file = dest_dir / "last_result.txt"
    result_q = _vbs_str(str(result_file))
    dest_q = _vbs_str(str(dest_dir))
    body = (
        "' LKL-Trade 自动更新桩：等托盘退出→静默安装→拉起新托盘\n"
        "On Error Resume Next\n"
        "Do\n"
        f"    Set p = GetObject(\"winmgmts:\\\\.\\root\\cimv2:Win32_Process.Handle='{tray_pid}'\")\n"
        "    If Err.Number <> 0 Then Exit Do\n"
        "    Err.Clear\n"
        "    WScript.Sleep 1000\n"
        "Loop\n"
        "On Error GoTo 0\n"
        "Set sh = CreateObject(\"WScript.Shell\")\n"
        f"rc = sh.Run(\"\"\"{setup_q}\"\"\" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-\", 0, True)\n"
        "On Error Resume Next\n"
        "Set fso = CreateObject(\"Scripting.FileSystemObject\")\n"
        f"fso.CreateFolder(\"\"\"{dest_q}\"\"\")\n"
        f"Set tf = fso.CreateTextFile(\"\"\"{result_q}\"\"\", 2, True)\n"
        "tf.WriteLine rc\n"
        "tf.Close\n"
        "On Error GoTo 0\n"
        f"sh.Run \"\"\"{tray_cmd_q}\"\"\", 0, False\n"
    )
    # UTF-16 LE 带 BOM：wscript 识别 Unicode 脚本（中文路径/注释不乱码）
    vbs.write_bytes(body.encode("utf-16"))
    return vbs