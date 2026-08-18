"""模型网关测试：重试/4xx不重试/录制回放/限流/超时（服务级降级（§3.7）/ 能力接口契约（§5.1.4））。"""
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


def test_rate_limit_throttles_per_second():
    """Worker 配额限流：每秒至多 QPS 次（§6.3/T25）。"""
    waits = []

    def fake_sleep(s):
        waits.append(s)

    gw = Gateway(sleep=fake_sleep, rate_limits={"vlm": 2})
    for _ in range(2):
        assert gw.call("vlm", lambda **kw: "ok", figure_id="f", trace_id="t") == "ok"
    # 第 3 次超出 QPS=2，应等待到下一窗口
    assert gw.call("vlm", lambda **kw: "ok", figure_id="f", trace_id="t") == "ok"
    assert len(waits) == 1
    assert 0 < waits[0] <= 1.0


def test_rate_limit_disabled_by_default():
    gw = Gateway()
    assert gw.rate_limits == {}
    for _ in range(5):  # 无配额则不限流
        assert gw.call("vlm", lambda **kw: "ok", figure_id="f", trace_id="t") == "ok"


def test_configurable_timeout():
    gw = Gateway(timeouts={"vlm": 5.0})
    assert gw.timeouts["vlm"] == 5.0
    assert gw.timeouts["sam"] == 20.0  # 未配置沿用默认
    gw2 = Gateway()
    assert gw2.timeouts["ocr"] == 10.0
