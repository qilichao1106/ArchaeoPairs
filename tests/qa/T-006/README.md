# T-006 frozen acceptance tests (verifier: dsh)

Synthetic-only acceptance suite for `archaeopairs.vision` (contour views,
COCO-style RLE, `View`).  No real book image, no network, no write outside
`tmp_path`.

Run from the project root (this worktree root)::

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-006 -q -p no:cacheprovider

Coverage map:

| File | Covers |
|---|---|
| `test_io.py` | `load_image` Chinese path, BGR decode |
| `test_segmentation.py` | two/four separated blocks + reading order, 3x3 noise (<15) vs 4x4 (>=15), hole filling / outer contour only, contained-contour removal, pure white -> `[]` |
| `test_mask_and_view.py` | bbox contains mask, `area == mask.sum`, contour fill rather than bbox rectangle, `mask_iou` same/disjoint/partial/shape mismatch, `View` fields, exports |
| `test_rle.py` | column-major round-trip, first run is background, malformed / wrong-total / negative / non-string RLE -> `ValueError` |
| `test_negative.py` | missing/empty/non-image/directory -> `OSError`, blank image and 3x3 speck -> no views, IoU shape mismatch -> `ValueError` |

`conftest.py` puts `src/` and this directory on `sys.path`; `synthetic.py`
holds the Pillow/numpy fixtures.