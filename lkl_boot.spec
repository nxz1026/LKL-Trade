# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)   # spec 所在目录（仓库根）；相对路径打包，CI 任意检出目录可构建

datas = [(str(ROOT / 'dashboard' / 'trade_index.html'), '.')]
binaries = []
hiddenimports = ['lkl.broker', 'lkl.supervisor', 'dashboard.trade_server']
tmp_ret = collect_all('grpc')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('protobuf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tzdata')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(ROOT / 'lkl_boot.py')],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PIL', 'pystray', 'Cython', 'cx_Freeze'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='lkl_boot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
# 托盘入口：windowed（无控制台窗口）。自启/快捷方式/托盘菜单全部经它；
# 服务进程（sup/dash）本就无窗口需求。CLI 仍走 console 版 lkl_boot.exe。
exe_tray = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='lkl_tray',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    exe_tray,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='lkl_boot',
)
