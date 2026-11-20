# T-009 frozen acceptance tests

Scope: `src/archaeopairs/naming.py` (AC-07) and
`src/archaeopairs/compose/render.py` (AC-05). Every image is synthetic
PIL/numpy data built in memory; no test reads `books/`, writes a file or opens
a socket.

## Run

From the project root:

```powershell
$env:PYTHONDONTWRITEBYTECODE=1
python -m pytest tests/qa/T-009 -q -p no:cacheprovider
```

## Files

| File | Covers |
|---|---|
| `test_naming.py` | figure numbers (`图2-1-16`, `图七`, `图二六`, `图版204`, `拓片三七`), suffixes (`图七a`, `图2-1-16b`), colons `: ： ∶`, `01` fallback, `_N` dedup, fallback captions |
| `test_compose.py` | two-view union mask, white background, exact source pixels, `pixel_mismatch=0`, `margin=max(6, round(3%))`, pure translation, scale bbox crop below content and centred, binding order, shared-bar repetition, `missing_scales`, `whole_image`, dict units/string keys, no-scale units |
| `test_compose_negative.py` | real faults that must raise `ComposeError`: empty mask, blank RLE, missing view, no `view_ids`, mask/image size mismatch, malformed RLE, empty/outside scale bbox, non-8-bit image |
| `t009_synthetic.py` | in-memory PIL/numpy figure, masks, RLE views, scale bars and binding dicts |
| `conftest.py` | puts `src/` and this directory on `sys.path` |

The negative file contains ten parametrised/fault-injection cases, above the
required minimum of five.