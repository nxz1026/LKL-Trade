"""掘金标准代码：A股交易代码 → 交易所前缀（SHSE./SZSE.）。

掘金下单用 "SHSE.600519" / "SZSE.000001" 形式，本模块负责转换。
"""
from __future__ import annotations


_SH = ("6", "9", "5")        # 沪A(600/601/603/605/688/689)/沪B(900)/沪基金ETF(5xx)
_SZ = ("0", "1", "2", "3")   # 深A(000/001/002/003)/深基金ETF(1xx)/深B(200)/创业板(300/301)


def to_gm_symbol(code: str) -> str:
    """已知段位 → SHSE./SZSE. 前缀；已有前缀原样返回；未知段位（4/8/920 北交所）拒绝。

    不下错单优先：北交所当前 gmtrade 无 BJSE 前缀支持，明确报错而非默认归入 SZSE。
    """
    code = str(code).strip()
    if "." in code:
        return code
    if code.startswith(("4", "8")) or code.startswith("920"):
        raise ValueError(f"无法识别 {code!r} 所属市场（4/8/920 开头为北交所，当前 gmtrade 不支持 BJSE）")
    if code.startswith(_SH):
        return f"SHSE.{code}"
    if code.startswith(_SZ):
        return f"SZSE.{code}"
    raise ValueError(f"无法识别 {code!r} 所属市场")