"""真实 VL 冒烟（手动，不入 pytest）：火山方舟 glm-5.3-flash 三态仲裁两入口。

用法: .venv/Scripts/python.exe -X utf8 scripts/vl_smoke.py [图片路径]
"""
import sys

from archaeopairs.capability.providers import VlArbiterService
from archaeopairs.config import load_providers
from archaeopairs.vision import load_image

IMG = sys.argv[1] if len(sys.argv) > 1 else "books/万州瓦子坪/media/image9.jpg"

load_providers()
bgr, _ = load_image(IMG)
svc = VlArbiterService(preset="glm-53-flash", cache_dir="runs/vl_cache")
same, note = svc.same_artifact(
    bgr=bgr, box_a=[100, 100, 300, 400], box_b=[350, 100, 550, 400],
    trace_id="smoke", figure_id=IMG)
print("same_artifact:", same, "|", note)
nums, note2 = svc.read_scale_prefix(
    bgr=bgr, scale={"bbox": [400, 1850, 1200, 1920], "raw_text": ""},
    where="smoke", trace_id="smoke", figure_id=IMG)
print("read_scale_prefix:", nums, "|", note2)
print("stats:", svc.stats().get("per_stage", {}).get("__total__"))
