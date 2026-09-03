"""掘金标准代码：A股交易代码 → 交易所前缀（SHSE./SZSE.）。

掘金下单用 "SHSE.600519" / "SZSE.000001" 形式，本模块负责转换。
"""
from __future__ import annotations


def to_gm_symbol(code: str) -> str:
    """600/601/603/605(sh) → SHSE；000/001/002 → SZSE；已有前缀原样返回。"""
    code = str(code).strip()
    if "." in code:
        return code
    prefix = "SHSE" if code.startswith(("6", "9", "5")) else "SZSE"
    return f"{prefix}.{code}"