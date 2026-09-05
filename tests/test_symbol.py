"""股票代码→交易所前缀映射测试（白名单：未知段位明确拒绝，绝不下错单）。"""
from __future__ import annotations

import pytest

from lkl.broker.symbol import to_gm_symbol


@pytest.mark.parametrize("code", [
    "600519", "601988", "603000", "605000", "688981", "689009",  # 沪A/科创板
    "900901", "900928",                                           # 沪B
    "510300", "511990", "512880", "588000",                        # 沪基金ETF
])
def test_sh_codes(code):
    assert to_gm_symbol(code) == f"SHSE.{code}"


@pytest.mark.parametrize("code", [
    "000001", "001234", "002594", "003816",                      # 深A
    "300750", "301236",                                            # 创业板
    "200011",                                                      # 深B
    "159915", "161725", "180801",                                  # 深基金ETF/REITs
])
def test_sz_codes(code):
    assert to_gm_symbol(code) == f"SZSE.{code}"


def test_prefixed_passthrough():
    assert to_gm_symbol("SHSE.600519") == "SHSE.600519"
    assert to_gm_symbol("SZSE.000001") == "SZSE.000001"


@pytest.mark.parametrize("code", ["830799", "430047", "920001", "870001", "430123"])
def test_unknown_segments_rejected(code):
    """北交所（4/8/920 开头）与未知段位：明确拒绝而非默认归 SZSE（gmtrade 无 BJSE）。"""
    with pytest.raises(ValueError):
        to_gm_symbol(code)