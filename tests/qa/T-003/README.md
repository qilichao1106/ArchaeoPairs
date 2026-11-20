# T-003 冻结验收测试（Verifier: dsh）

对象：`agent-orchestration workspace/collab/cards/T-003.md`
（图注解析 + seq→artifact 映射 + 正文切分入口，AC-02）。

运行（项目根，即本 worktree 根）：

```text
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-003 -q -p no:cacheprovider
```

本目录是验证者写权范围（`tests/qa/T-003/`）；断言不得放宽/删除/跳过。

## 覆盖矩阵

| 卡要求 | 测试 |
|---|---|
| `:`/`：`/`∶` 归一、冒号旁空白折叠 | `test_artifact_id.py::test_normalize_artifact_id` |
| 大小写、`75a` 后缀、`8-1` 子编号保留 | `test_artifact_id.py::test_normalize_preserves_suffix_letters_and_subnumbers` |
| 抽取 `M4:6`/`2004CWWM11：5`/`M43:75a`/`M39:8-1`/`00FBH1:6` | `test_artifact_id.py::test_extract_artifact_id_shapes` |
| 出现顺序 + 去重 | `test_artifact_id.py::test_extract_keeps_first_appearance_order_and_dedupes` |
| 后缀字母/子编号各自独立，不并到词干 | `test_artifact_id.py::test_suffix_letters_and_subnumbers_are_independent_artifacts` |
| 比例尺/汉字图号/图号子编号/`Bb9` 不是器物号 | `test_artifact_id.py::test_non_artifact_text_never_produces_an_id`、`test_negative_inputs.py::test_negative_scale_and_figure_numbers_are_not_artifact_ids`、`::test_negative_bare_prefixed_name_is_evidence_only` |
| `1.骨笄`、空格分隔多条目 | `test_note.py::test_dot_clause_without_space`、`::test_two_dot_clauses_separated_by_space` |
| `1. 骨笄（M4:1）`、`1、2.` 组列 | `test_note.py::test_single_artifact_in_parentheses`、`::test_parenthesised_artifact_id_and_grouped_seq` |
| `1～4.`、`3～5、9.` 区间展开 | `test_note.py::test_range_seq_expands_and_keeps_id_order`、`::test_grouped_range_seq_expands_including_disjoint_number` |
| `A.` 字母序号（`seq_list` 可空） | `test_note.py::test_letter_seq_is_kept_with_empty_seq_list` |
| `①`/`①、②` 圈号 | `test_note.py::test_circled_seq_maps_to_arabic_number`、`::test_circled_group_accumulates_into_one_clause` |
| `$1\sim 4$ 陶豆 5.陶壶` | `test_note.py::test_tex_range_form_and_following_clause` |
| `1.00FBG1:2` 无空格 | `test_note.py::test_glued_artifact_id_without_space` |
| `3～7.` 无器物号条目 | `test_note.py::test_clause_may_have_no_artifact_id` |
| 多 note 段换行合并 | `test_note.py::test_newline_merged_note_segments_parse_as_clauses` |
| `0 8厘米` 比例尺噪声 | `test_note.py::test_scale_noise_and_text_without_clauses_yield_no_items` |
| 图题兜底抽取 | `test_note.py::test_caption_fallback_extracts_title_artifacts`、`::test_caption_without_artifacts_is_empty` |
| 1:1 → `rule_a` | `test_mapping.py::test_one_seq_one_artifact_is_rule_a` |
| N:1 → `rule_b` | `test_mapping.py::test_n_seq_one_artifact_is_rule_b` |
| 1:N → `split_same_seq` | `test_mapping.py::test_one_seq_many_artifacts_is_split_same_seq` |
| N:N 位置对应 → `rule_a` | `test_mapping.py::test_n_seq_n_artifact_positional_zip_is_rule_a` |
| 区间 N:N → `range_split` | `test_mapping.py::test_n_seq_n_artifact_range_zip_is_range_split` |
| 图注优先、图题仅兜底 | `test_mapping.py::test_figure_note_wins_over_caption_title`、`::test_caption_title_is_the_fallback_when_note_has_no_id` |
| 两者都无 → `seq_missing`（degraded） | `test_mapping.py::test_missing_note_and_caption_degrade_to_seq_missing` |
| 数量不一致 → 冲突、不猜测 | `test_mapping.py::test_count_mismatch_is_a_conflict_and_never_paired` |
| 同 artifact 多 seq → 冲突（证据保留） | `test_mapping.py::test_same_artifact_on_two_seqs_is_a_conflict_but_evidence_is_kept` |
| 正文独有器物不配 seq | `test_mapping.py::test_body_only_artifact_is_recorded_not_paired_with_a_seq` |
| split_body 单锚点整段归属 | `test_body.py::test_single_anchor_keeps_the_whole_paragraph` |
| split_body 多锚点按标本/句界切分 | `test_body.py::test_multiple_anchors_are_cut_into_their_own_slices` |
| split_body 无锚点挂最近上文 | `test_body.py::test_no_anchor_paragraph_hangs_on_the_previous_anchor` |
| split_body 首段无锚点丢弃 | `test_body.py::test_leading_no_anchor_paragraph_is_dropped` |
| split_body 接受 dict 段落 | `test_body.py::test_dict_paragraphs_are_accepted` |

## 负向对照（真实故障可由绿转红）

- `test_negative_inputs.py::test_negative_scale_and_figure_numbers_are_not_artifact_ids`
  —— 比例尺/图号不得被当成器物号。
- `test_negative_inputs.py::test_negative_bare_prefixed_name_is_evidence_only`
  —— `Bb9`/字母条目只作名称证据，不得产生 artifact_id。
- `test_negative_inputs.py::test_negative_count_mismatch_is_a_conflict_not_a_pairing`
  —— 2 seq / 3 art 不得被猜成 zip 或笛卡尔积。
- `test_negative_inputs.py::test_negative_text_without_seq_or_artifact_yields_nothing`
  —— 无序号、无器物号的说明文本不得产生 NoteItem。
- `test_negative_inputs.py::test_negative_unattributable_body_paragraph_is_dropped`
  —— 首个锚点之前的无锚点段不得挂到不存在的上文物。

## 状态（如实记录）

- 2026-11-20 实跑结果：`69 passed, exit 0；负向对照：恢复区间 bug → 2 failed，恢复修复 → 69 passed；AC-02 pass`。
- `M39:8-1` 的 `_RANGE_RE` 缺陷（曾把 `8-1` 当区间替换为空，导致 `_ID_RE`
  抽不到该 id）已由实现修复。
- 另：`extract_artifacts("标本M43：75a……75b……75c")` 只返回 `M43:75a`（裸 `75b`
  被 `artifact_id.py:121-126` 当作名称证据跳过），与模块 docstring 的 R-ID-06
  续号说明不一致；卡 §1 的括号规则未明确要求续号，故未写成断言，仅登记风险。