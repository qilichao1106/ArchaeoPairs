"""模型网关测试：重试/4xx不重试/熔断恢复/成本帽/有界统计（服务级降级与熔断（§3.7）/ 单图成本帽（§5.9.3））。"""
from __future__ import annotations

import pytest

from archaeopairs.errors import E401OcrMissKeySeqError
from archaeopairs.gateway import CostCapExceeded, Gateway


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


def test_circuit_open_after_threshold():
    def bad(**kw):
        raise TimeoutError("t")

    gw = Gateway(circuit_threshold=2, sleep=lambda s: None)
    for _ in range(2):
        with pytest.raises(TimeoutError):
            gw.call("sam", bad, figure_id="f", trace_id="t")
    from archaeopairs.errors import E1000ServiceUnavailableError
    with pytest.raises(E1000ServiceUnavailableError):
        gw.call("sam", lambda **kw: "ok", figure_id="f", trace_id="t")


def test_cost_cap_exceeded():
    gw = Gateway(per_figure_cap_cny=1.0)
    gw.cost_by_figure["f"] = 1.0
    with pytest.raises(CostCapExceeded):
        gw.call("vlm", lambda **kw: "ok", figure_id="f", trace_id="t")


def test_reset_figure_bounded():
    gw = Gateway()
    gw.cost_by_figure["f"] = 0.5
    gw.reset_figure("f")
    assert "f" not in gw.cost_by_figure


def test_call_accumulates_cost():
    gw = Gateway()
    gw.call("vlm", lambda **kw: "ok", figure_id="f", trace_id="t", cost=0.2,
            operation="classify", iteration=0)
    assert gw.cost_by_figure["f"] == 0.2


def test_replay_key_uses_operation_and_iteration():
    gw = Gateway(replay={"vlm:classify:f:0": "ok"})
    assert gw.call("vlm", lambda **kw: "live", figure_id="f", trace_id="t",
                   operation="classify", iteration=0) == "ok"
