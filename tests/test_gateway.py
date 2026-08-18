"""模型网关测试：重试/4xx不重试/录制回放（服务级降级（§3.7））。"""
from __future__ import annotations

import pytest

from archaeopairs.errors import E401OcrMissKeySeqError
from archaeopairs.gateway import Gateway


def test_retry_on_retryable_then_success():
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("timeout")
        return "ok"

    gw = Gateway(sleep=lambda s: None)
    assert gw.call("vlm", flaky, figure_id="f", trace_id="t") == "ok"
    assert calls["n"] == 3


def test_no_retry_on_4xx():
    def bad(**kw):
        raise E401OcrMissKeySeqError("4xx")

    gw = Gateway(sleep=lambda s: None)
    with pytest.raises(E401OcrMissKeySeqError):
        gw.call("ocr", bad, figure_id="f", trace_id="t")






def test_replay_key_uses_operation_and_iteration():
    gw = Gateway(replay={"vlm:classify:f:0": "ok"})
    assert gw.call("vlm", lambda **kw: "live", figure_id="f", trace_id="t",
                   operation="classify", iteration=0) == "ok"
