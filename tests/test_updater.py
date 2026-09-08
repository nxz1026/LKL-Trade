"""自动更新单元测试：版本比较 / version.json 解析 / 下载校验 / VBS 更新桩 / 配置读取。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _ver_cmp():
    from lkl.broker import updater
    return updater.ver_cmp


def test_ver_cmp_equal():
    assert _ver_cmp()("1.0.0", "1.0.0") == 0


def test_ver_cmp_ordering():
    c = _ver_cmp()
    assert c("1.0.1", "1.0.0") == 1
    assert c("1.0.0", "1.0.1") == -1
    assert c("1.1.0", "2.0.0") == -1
    assert c("2.0", "1.9.9") == 1          # 段数不同可比较
    assert c("v1.10.0", "v1.9.9") == 1     # 数值比较：10 > 9


def test_ver_cmp_prerelease():
    c = _ver_cmp()
    assert c("1.1.0-beta", "1.1.0") == -1  # 预发布小于正式版
    assert c("1.1.0", "1.1.0-beta") == 1
    assert c("1.1.0-rc2", "1.1.0-rc1") == 1
    assert c("1.1.0-beta", "1.1.0-rc") == -1  # 字符串兜底：beta < rc（alpha<beta<rc）


def test_parse_version_json():
    from lkl.broker import updater
    info = updater.parse_version_json(
        '{"version": "1.1.0", "url": "LKL-Trade-Setup-1.1.0.exe", "sha256": "AB12", "note": "x"}')
    assert info == {"version": "1.1.0", "url": "LKL-Trade-Setup-1.1.0.exe",
                    "sha256": "ab12", "note": "x"}   # sha256 转小写


def test_parse_version_json_missing_field():
    from lkl.broker import updater
    with pytest.raises(ValueError):
        updater.parse_version_json('{"version": "1.1.0"}')   # 缺 url
    with pytest.raises(ValueError):
        updater.parse_version_json('{"url": "a.exe"}')       # 缺 version
    with pytest.raises(ValueError):
        updater.parse_version_json('["not", "object"]')      # 非对象
    with pytest.raises(ValueError):
        updater.parse_version_json("{broken")                # 坏 JSON


def test_check_file_url(tmp_path):
    from lkl.broker import updater
    (tmp_path / "version.json").write_text(
        json.dumps({"version": "1.1.0", "url": "LKL-Trade-Setup-1.1.0.exe"}), encoding="utf-8")
    info = updater.check(tmp_path.as_uri(), "1.0.0")
    assert info["version"] == "1.1.0"
    assert info["url"].endswith("/LKL-Trade-Setup-1.1.0.exe")  # 相对路径已拼全
    assert info["url"].startswith("file://")
    assert updater.check(tmp_path.as_uri(), "1.1.0") is None   # 同版本
    assert updater.check(tmp_path.as_uri(), "1.2.0") is None   # 本地更高


def test_check_unreachable():
    """更新源不可达 → UpdaterError（网络/文件不存在统一语义）。"""
    from lkl.broker import updater
    with pytest.raises(updater.UpdaterError, match="不可达"):
        updater.check("file:///Z:/no/such/dir", "1.0.0")


def test_download_ok(tmp_path):
    from lkl.broker import updater
    src = tmp_path / "setup.exe"
    data = b"installer-bytes"
    src.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    dest = updater.download(tmp_path.as_uri() + "/setup.exe", tmp_path / "dl", sha256=sha)
    assert dest.read_bytes() == data
    assert dest.name == "setup.exe"


def test_download_bad_sha_cleans_part(tmp_path):
    from lkl.broker import updater
    src = tmp_path / "setup.exe"
    src.write_bytes(b"data")
    with pytest.raises(updater.UpdaterError, match="校验和不匹配"):
        updater.download(tmp_path.as_uri() + "/setup.exe", tmp_path / "dl",
                         sha256="0" * 64)
    assert not (tmp_path / "dl" / "setup.exe.part").exists()   # 残件已清理


def test_download_over_limit_cleans_part(tmp_path):
    from lkl.broker import updater
    src = tmp_path / "setup.exe"
    src.write_bytes(b"f" * 100)
    with pytest.raises(updater.UpdaterError, match="上限"):
        updater.download(tmp_path.as_uri() + "/setup.exe", tmp_path / "dl", max_bytes=50)
    assert not (tmp_path / "dl" / "setup.exe.part").exists()
    # 边界：正好等于上限允许
    ok = updater.download(tmp_path.as_uri() + "/setup.exe", tmp_path / "dl2", max_bytes=100)
    assert ok.read_bytes() == b"f" * 100


def test_write_vbs_content(tmp_path):
    from lkl.broker import updater
    setup = tmp_path / "LKL-Trade-Setup-1.1.0.exe"
    setup.write_bytes(b"x")
    vbs = updater.write_vbs(setup, 12345, '"C:\\LKL-Trade\\lkl_tray.exe" tray', tmp_path / "upd")
    raw = vbs.read_bytes()
    assert raw[:2] == b"\xff\xfe"                      # UTF-16 LE BOM（wscript 识别）
    body = raw.decode("utf-16")
    assert "Win32_Process.Handle='12345'" in body      # 等托盘 PID 消失
    assert "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-" in body
    assert "lkl_tray.exe" in body
    assert "last_result.txt" in body
    assert str(setup).replace('"', '""') in body       # 引号转义（含空格路径）


def test_write_vbs_chinese_path(tmp_path):
    """中文安装路径：UTF-16 保证 wscript 不乱码。"""
    from lkl.broker import updater
    setup = tmp_path / "LKL-Trade-Setup-1.1.0.exe"
    setup.write_bytes(b"x")
    vbs = updater.write_vbs(setup, 9, '"C:\\用户\\张三\\LKL-Trade\\lkl_tray.exe" tray', tmp_path)
    assert "张三" in vbs.read_bytes().decode("utf-16")


def test_write_vbs_default_dir():
    """缺省 dest_dir → %TEMP%/lkl-update（安装目录之外，更新期间不被覆盖锁定）。"""
    from lkl.broker import updater
    import tempfile
    setup = Path(tempfile.gettempdir()) / "LKL-Trade-Setup-1.1.0.exe"
    vbs = updater.write_vbs(setup, 1, '"C:\\LKL\\lkl_tray.exe" tray')
    assert "lkl-update" in vbs.read_bytes().decode("utf-16")
    assert vbs.parent.name == "lkl-update"


def test_config_update_settings(tmp_path, monkeypatch):
    """更新配置经 env 或配置文件读取，默认值合理。"""
    from lkl.broker import config
    monkeypatch.setenv("GM_UPDATE_URL", "https://up.example.com/lkl")
    monkeypatch.setenv("GM_UPDATE_INTERVAL_HOURS", "2")
    monkeypatch.setenv("GM_UPDATE_AUTO", "1")
    assert config.update_url() == "https://up.example.com/lkl"
    assert config.update_interval_hours() == 2
    assert config.update_auto() is True
    # 非法间隔回退默认 6；auto 非 1 为 False
    monkeypatch.setenv("GM_UPDATE_INTERVAL_HOURS", "abc")
    assert config.update_interval_hours() == 6
    monkeypatch.setenv("GM_UPDATE_AUTO", "0")
    assert config.update_auto() is False
    # 未配置时默认 6 / False
    monkeypatch.delenv("GM_UPDATE_URL")
    monkeypatch.delenv("GM_UPDATE_INTERVAL_HOURS")
    assert config.update_interval_hours() == 6
    assert config.update_auto() is False
    assert config.APP_VERSION  # 版本常量非空


def test_version_single_source(tmp_path):
    """version.py 与 installer.iss 版本号一致（发布构建自动同步的唯一来源）。"""
    from pathlib import Path
    import re
    from lkl.broker.version import __version__
    iss = Path(__file__).resolve().parents[1] / "installer.iss"
    m = re.search(r'#define MyAppVersion "([^"]+)"', iss.read_text(encoding="utf-8"))
    assert m, "installer.iss 缺 MyAppVersion"
    assert m.group(1) == __version__