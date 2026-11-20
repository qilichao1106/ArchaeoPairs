# T-004 冻结验收测试（Verifier: dsh）

对象：`agent-orchestration workspace/collab/cards/T-004.md`
（VLM 客户端 + 结构化 OCR provider，AC-03）。

运行（项目根，即本 worktree 根）：

```text
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-004 -q -p no:cacheprovider
```

本目录是验证者写权范围（`tests/qa/T-004/`）；断言不得放宽/删除/跳过。
所有 HTTP 流量都走 `httpx.MockTransport`，OCR provider 用 fake client；
测试不读取真实 API Key，也不访问真实网络。

## 覆盖矩阵

| 卡要求 / 用户验收点 | 测试 |
|---|---|
| 缺 key → `VlmUnavailableError`，且不发出请求 | `test_vlm_client.py::test_missing_api_key_raises_unavailable_without_request` |
| 成功 JSON → 返回 assistant 文本 | `test_vlm_client.py::test_chat_success_sends_contract_request_and_returns_content` |
| 请求结构：POST `/chat/completions`、Bearer、model、messages、`response_format` | 同上 |
| 4xx → 立即 `VlmError`，带 status_code，不重试 | `test_vlm_client.py::test_chat_4xx_raises_immediately_without_retry`（400/401/404/422） |
| 429 / 5xx → 指数退避重试后成功 | `test_vlm_client.py::test_retryable_status_retries_then_succeeds`（429/500/503） |
| 429 / 5xx → 预算耗尽后报错 | `test_vlm_client.py::test_retryable_status_exhausts_retry_budget`（429/500） |
| `content: null` → 重试后成功 | `test_vlm_client.py::test_null_content_is_retried_then_succeeds` |
| `content: null` → 预算耗尽后报错 | `test_vlm_client.py::test_null_content_exhausts_retry_budget` |
| 超时不重试 | `test_vlm_client.py::test_timeout_is_not_retried` |
| `last_usage` / `last_latency_ms` 记录 usage 与耗时 | `test_vlm_client.py::test_chat_records_usage_and_positive_latency` |
| `describe_image` 请求结构：text + image_url，PNG base64 data URL | `test_vlm_client.py::test_describe_image_sends_text_then_png_data_url` |
| `describe_image(json_mode=False)` 不带 `response_format` | `test_vlm_client.py::test_describe_image_respects_json_mode_false` |
| 默认 base_url/model、环境变量覆盖 | `test_vlm_client.py::test_default_base_url_and_model`、`::test_environment_base_url_and_key_override` |
| 合法 OCR JSON → `OcrResult(source="vlm")`，raw 保留 | `test_vlm_ocr.py::test_valid_json_is_parsed_into_a_vlm_ocr_result` |
| Markdown fence（``` / ```json / ```JSON） | `test_vlm_ocr.py::test_markdown_fence_is_tolerated` |
| 非法 JSON / 非对象 JSON → `OcrError` | `test_vlm_ocr.py::test_invalid_json_raises_ocr_error` |
| 坏 bbox（长度、反向、非数字、bool） → `OcrError` | `test_vlm_ocr.py::test_bad_bbox_raises_ocr_error` |
| 必需字段缺失或类型错误 → `OcrError` | `test_vlm_ocr.py::test_missing_or_mistyped_required_fields_raise_ocr_error` |
| 空图/无文本 → 合法空 `OcrResult` | `test_vlm_ocr.py::test_empty_payload_is_a_legal_empty_ocr_result` |
| client 异常包装为 `OcrError` | `test_vlm_ocr.py::test_client_failure_is_wrapped_in_ocr_error`、`::test_non_text_reply_raises_ocr_error` |
| `OCRProvider` Protocol | `test_vlm_ocr.py::test_provider_satisfies_the_ocr_protocol` |
| merge 去重（同 text+bbox，primary 顺序优先） | `test_merge.py::test_identical_text_and_bbox_are_deduplicated_primary_order_wins` |
| 同 bbox 不同 text 不去重 | `test_merge.py::test_same_bbox_with_different_text_is_not_deduplicated` |
| 同 text 不同 bbox 保留两条并写 `raw["conflicts"]` | `test_merge.py::test_same_text_at_different_bbox_is_kept_and_reported_as_a_conflict` |
| scales/texts 合并、空结果合并、`source="hybrid"` | `test_merge.py::test_scales_and_texts_are_merged_and_deduplicated`、`::test_empty_results_merge_into_an_empty_hybrid_result` |
| 提示词要求 JSON、结构字段、不得猜测 | `test_prompts.py`（OCR / VISUAL / QC） |
| 不泄露 key（异常、repr、日志、OCR 包装） | `test_secret_hygiene.py` |

## 负向对照（真实故障可由绿转红）

- `test_vlm_client.py::test_missing_api_key_raises_unavailable_without_request`
  —— 没 key 仍发请求，测试会失败。
- `test_vlm_client.py::test_chat_4xx_raises_immediately_without_retry`
  —— 4xx 被重试或未带 status_code，测试会失败。
- `test_vlm_client.py::test_null_content_is_retried_then_succeeds`
  —— `content: null` 被当成成功文本，测试会失败。
- `test_vlm_ocr.py::test_invalid_json_raises_ocr_error`
  —— 非法 JSON 静默返回空结果，测试会失败。
- `test_vlm_ocr.py::test_bad_bbox_raises_ocr_error`
  —— 3 元/反向/非数字/bool bbox 被接受，测试会失败。
- `test_vlm_ocr.py::test_missing_or_mistyped_required_fields_raise_ocr_error`
  —— 缺 `text`/`bbox` 被容错成空值，测试会失败。
- `test_merge.py::test_same_text_at_different_bbox_is_kept_and_reported_as_a_conflict`
  —— 冲突被静默去重，测试会失败。
- `test_secret_hygiene.py`
  —— 异常/repr/日志/OCR 包装回显 sentinel key，测试会失败。

## 状态（如实记录）

- 2026-11-20：**实跑通过**。`59 passed, exit 0；负向对照：注入不重试 429/5xx → 5 failed，恢复 → 59 passed；AC-03 pass`。