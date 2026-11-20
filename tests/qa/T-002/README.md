# T-002 冻结验收测试（Verifier: dsh）

对象：卡 `agent-orchestration workspace/collab/cards/T-002.md`
（XML 摄入 + FigureInput + 器物号计数 + 五分类 → 四工作线）。

运行（项目根，即本 worktree 根）：

```text
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-002 -q -p no:cacheprovider
```

本目录是验证者写权范围（`tests/qa/T-002/`）；断言不得放宽/删除/跳过。

## 覆盖矩阵

| 卡要求 | 测试 |
|---|---|
| 命名空间无关（默认 ns / 无 ns） | `test_parse_book.py::test_parse_book_namespaced_keeps_titles_notes_body_and_media`、`::test_parse_book_without_namespace` |
| title/note 仅取 figure 直接子节点；多 note 换行合并 | `test_parse_book.py::test_parse_book_namespaced_keeps_titles_notes_body_and_media`、`::test_parse_book_only_direct_children_and_skips_invalid_figures` |
| 缺失图题/图注为 None（不猜测） | `test_parse_book.py::test_parse_book_only_direct_children_and_skips_invalid_figures` |
| body_paras 收集全部非空 para，p1..pN 连续 | `test_parse_book.py::test_parse_book_namespaced_keeps_titles_notes_body_and_media` |
| 无 imagedata / fileref 缺失或空白 → 跳过 | `test_parse_book.py::test_parse_book_only_direct_children_and_skips_invalid_figures`、`::test_negative_control_figures_without_media_never_appear` |
| `figure_id = book_id:stem(fileref)`，book_id 命名空间 | `test_parse_book.py::test_parse_book_namespaces_figure_id_by_book_id` |
| `media_path = media_root/fileref`，默认 XML 目录；中文路径 | `test_parse_book.py::test_parse_book_media_root_override_with_chinese_paths` |
| 图注优先、图题兜底、归一化去重 | `test_count_artifacts.py::test_count_artifacts` |
| `M43:75a/b/c`、`M39:8-1` 后缀独立 | `test_count_artifacts.py::test_count_artifacts` |
| 比例尺/图号不计入器物号 | `test_count_artifacts.py::test_negative_control_scale_and_figure_number_are_not_artifacts` |
| N=0 → discarded | `test_classify.py::test_zero_artifacts_is_discarded_regardless_of_pixels`、`::test_negative_control_no_artifact_never_gets_a_line_work_line` |
| 线图/灰度照片/彩色照片 × 单/多 | `test_classify.py::test_single_artifact_family`、`::test_multi_artifact_family` |
| 拓图词：gray→line，color 不覆盖 | `test_classify.py::test_rub_word_on_gray_photo_forces_line`、`::test_rub_word_does_not_override_color` |
| 缺失/不可读图像按图版关键词回退 | `test_classify.py::test_missing_image_with_plate_keyword_falls_back_to_plate`、`::test_unreadable_image_with_plate_keyword_falls_back_to_plate`、`::test_missing_image_without_plate_keyword_falls_back_to_line`、`::test_rub_word_overrides_plate_keyword_when_image_is_missing` |
| `work_line_of` 四线映射 | `test_models.py::test_work_line_of_four_line_mapping` |
| ImageType/WorkLine/FigureInput 冻结字段 | `test_models.py::test_image_type_has_exactly_the_five_frozen_values`、`::test_work_line_has_exactly_the_four_frozen_values`、`::test_figure_input_exposes_the_frozen_fields` |

## 负向对照

- `test_count_artifacts.py::test_negative_control_scale_and_figure_number_are_not_artifacts`
  —— 比例尺/图号/汉字图版号必须计为 0，防止“任意数字都算器物”。
- `test_classify.py::test_negative_control_no_artifact_never_gets_a_line_work_line`
  —— 即使线图像素完美，无器物号也必须 `discarded → archive`，防止像素证据越权。
- `test_parse_book.py::test_negative_control_figures_without_media_never_appear`
  —— 仅有 figure 节点、无 imagedata/fileref 的条目不得产出 FigureInput。

## 状态

测试已写入；执行结果以 worktree handoff 为准（本 worktree 的 shell 被 Windows
文件权限阻塞时为“未执行”，不得宣称通过）。`probe_write.tmp` 是 ACL 探测遗留的
临时文件，可删除，不被 pytest 收集。