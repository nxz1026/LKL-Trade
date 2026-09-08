"""版本号单一来源：构建（build_release）与运行时（托盘更新检查）共用。

与 installer.iss 的 MyAppVersion 同步由 scripts/build_release.py 自动改写，
手改本文件即可；禁止另开版本常量。
"""
from __future__ import annotations

__version__ = "1.0.0"