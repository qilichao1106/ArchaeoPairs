"""Self-check for T-004: VLM client, prompts, VLM OCR parsing and hybrid merge.

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-004/selfcheck_t004.py

All traffic goes through ``httpx.MockTransport`` / fake clients: no real
network or model call is made.  The UTF-8 log is written by this script.
"""

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from archaeopairs.models import OcrResult, ScaleBar, SeqLabel, TextBlock  # noqa: E402
from archaeopairs.ocr.base import OCRProvider, merge_ocr_results  # noqa: E402
from archaeopairs.ocr.vlm import OcrError, VlmOCRProvider  # noqa: E402
from archaeopairs.vlm import client as vlm_mod  # noqa: E402
from archaeopairs.vlm.client import (  # noqa: E402
    DEFAULT_BASE_URL, DEFAULT_MODEL, VlmClient, VlmError, VlmUnavailableError)
from archaeopairs.vlm.prompts import OCR_PROMPT, QC_PROMPT, VISUAL_PROMPT  # noqa: E402

LOG, PNG = (Path(__file__).with_name(n) for n in ("selfcheck.log", "_tiny.png"))
MSG = [{"role": "user", "content": "hi"}]
VALID = {
    "seqs": [{"text": "1", "bbox": [10, 20, 30, 40], "conf": 0.9}],
    "scales": [{"text": "0 8厘米", "bbox": [1, 2, 3, 4], "value": 8, "unit": "厘米",
                "prefix_nos": ["1"]}],
    "texts": [{"text": "盖顶面纹饰", "bbox": [5, 6, 7, 8]}],
}


def reply(content, status=200):
    return httpx.Response(status, json={
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}})


def client(handler):
    return VlmClient(api_key="k", transport=httpx.MockTransport(handler))
def raises(exc_type, call):
    try:
        call()
    except exc_type as exc:
        return exc
    raise AssertionError(f"{exc_type.__name__} not raised")


class Fake:
    def __init__(self, text):
        self.text, self.calls = text, []

    def describe_image(self, image_path, prompt, *, json_mode=True):
        self.calls.append((prompt, json_mode))
        return self.text


def check_missing_key():
    c = VlmClient(api_key="", transport=httpx.MockTransport(lambda r: reply("x")))
    exc = raises(VlmUnavailableError, lambda: c.chat(MSG))
    assert (c.model, c.base_url) == (DEFAULT_MODEL, DEFAULT_BASE_URL)
    assert "DASHSCOPE_API_KEY" in str(exc) and "sk-" not in str(exc)


def check_success_and_describe():
    seen = {}

    def handler(request):
        body = json.loads(request.content)
        seen.update(url=str(request.url), auth=request.headers["authorization"], body=body)
        return reply(json.dumps(VALID))

    c = client(handler)
    assert json.loads(c.chat(MSG, json_mode=True)) == VALID
    assert (seen["url"], seen["auth"]) == (DEFAULT_BASE_URL + "/chat/completions", "Bearer k")
    assert seen["body"]["model"] == DEFAULT_MODEL
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert c.last_usage["total_tokens"] == 10 and c.last_latency_ms >= 0
    c.describe_image(PNG, "看图", json_mode=False)
    content = seen["body"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "看图"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    raises(VlmError, lambda: c.describe_image(PNG.with_name("_absent.png"), "x"))


def check_invalid_json():
    assert client(lambda r: reply("not json")).chat(MSG) == "not json"
    exc = raises(OcrError, lambda: VlmOCRProvider(client(lambda r: reply("not json"))).read(PNG))
    assert "JSON" in str(exc)


def check_retries_and_errors():
    original, vlm_mod.time.sleep = vlm_mod.time.sleep, lambda s: None
    try:
        calls = []

        def flaky(request):
            calls.append(1)
            return reply("busy", 429) if len(calls) == 1 else reply(json.dumps(VALID))

        assert json.loads(client(flaky).chat(MSG)) == VALID and len(calls) == 2
        nulls = []

        def null_then_ok(request):
            nulls.append(1)
            return (httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
                    if len(nulls) == 1 else reply(json.dumps(VALID)))

        assert json.loads(client(null_then_ok).chat(MSG)) == VALID and len(nulls) == 2
        attempts = []

        def down(request):
            attempts.append(1)
            return reply("no", 500)

        exc = raises(VlmError, lambda: client(down).chat(MSG, max_retries=2))
        assert exc.status_code == 500 and len(attempts) == 3
        assert raises(VlmError, lambda: client(lambda r: reply("no", 400)).chat(MSG)).status_code == 400
        raises(VlmError, lambda: client(lambda r: (_ for _ in ()).throw(
            httpx.ReadTimeout("slow", request=r))).chat(MSG))
    finally:
        vlm_mod.time.sleep = original


def check_ocr_parse():
    fake = Fake("```json\n" + json.dumps(VALID) + "\n```")
    provider = VlmOCRProvider(fake)
    result = provider.read(PNG)
    assert isinstance(provider, OCRProvider) and result.source == "vlm" and result.raw == VALID
    assert result.seqs == [SeqLabel(text="1", bbox=(10, 20, 30, 40), conf=0.9)]
    assert result.scales == [ScaleBar(text="0 8厘米", bbox=(1, 2, 3, 4), value=8.0,
                                     unit="厘米", prefix_nos=["1"])]
    assert result.texts == [TextBlock(text="盖顶面纹饰", bbox=(5, 6, 7, 8))]
    assert fake.calls == [(OCR_PROMPT, True)]


def check_ocr_errors_and_empty():
    bad = [{"seqs": [{"text": "1", "bbox": [1, 2, 3]}]},
           {"seqs": [{"bbox": [1, 2, 3, 4]}]},
           {"texts": [{"text": "x", "bbox": ["a", 2, 3, 4]}]},
           {"scales": "nope"}, [1, 2, 3]]
    for payload in bad:
        raises(OcrError, lambda p=payload: VlmOCRProvider(Fake(json.dumps(p))).read(PNG))
    empty = VlmOCRProvider(Fake('{"seqs":[],"scales":[],"texts":[]}')).read(PNG)
    assert empty == OcrResult(source="vlm", raw={"seqs": [], "scales": [], "texts": []})


def check_merge():
    primary = OcrResult(seqs=[SeqLabel(text="1", bbox=(0, 0, 10, 10))],
                        texts=[TextBlock(text="铭文", bbox=(0, 20, 5, 25))],
                        source="vlm", raw={"k": 1})
    secondary = OcrResult(
        seqs=[SeqLabel(text="1", bbox=(0, 0, 10, 10)),
              SeqLabel(text="2", bbox=(15, 0, 20, 10))],
        scales=[ScaleBar(text="0 8厘米", bbox=(0, 30, 40, 40), value=8, unit="厘米")],
        texts=[TextBlock(text="铭文", bbox=(1, 21, 6, 26))], source="paddle", raw={"k": 2})
    merged = merge_ocr_results(primary, secondary)
    assert merged.source == "hybrid"
    assert [s.text for s in merged.seqs] == ["1", "2"]
    assert [t.text for t in merged.texts] == ["铭文", "铭文"]
    conflicts = merged.raw["conflicts"]
    assert len(conflicts) == 1 and conflicts[0]["text"] == "铭文", conflicts
    assert conflicts[0]["bboxes"] == [[0, 20, 5, 25], [1, 21, 6, 26]]
    assert merged.raw["primary"] == primary.model_dump()


def check_prompts():
    for prompt in (OCR_PROMPT, VISUAL_PROMPT, QC_PROMPT):
        assert "JSON" in prompt and "不要猜测" in prompt and '"bbox"' in prompt
    assert "切分" in VISUAL_PROMPT and "比例尺" in VISUAL_PROMPT


def main() -> int:
    PNG.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452" "000000010000000108060000001f15c489"
        "0000000d4944415478da63f8cfc000000301010" "0189dd4ee0000000049454e44ae426082"))
    log = open(LOG, "w", encoding="utf-8", newline="\n")
    try:
        for check in (check_missing_key, check_success_and_describe, check_invalid_json,
                      check_retries_and_errors, check_ocr_parse,
                      check_ocr_errors_and_empty, check_merge, check_prompts):
            log.write(f"RUN {check.__name__}\n")
            log.flush()
            check()
        log.write("SELFCHECK OK\n")
    finally:
        log.close()
        PNG.unlink(missing_ok=True)
    print("SELFCHECK OK (8 checks; log: selfcheck/T-004/selfcheck.log)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
