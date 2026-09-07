from __future__ import annotations

from archaeopairs.config import ProviderSettings


def test_provider_defaults_enable_ark_vl():
    settings = ProviderSettings()
    assert settings.vl == "ark"
    assert settings.sam == "mock"
    assert settings.ocr == "mock"
    assert settings.compositor == "mock"


def test_provider_vl_can_be_disabled():
    assert ProviderSettings(vl="mock").vl == "mock"
