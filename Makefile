.PHONY: doctor board help

help:
	@echo "make doctor  - 检查工具/配置/目录基线（退出 0 为通过）"
	@echo "make board   - 打印当前协同看板"

doctor:
	python scripts/preflight.py

board:
	python -c "import json,pathlib;print(json.dumps(json.loads(pathlib.Path('collab/board.json').read_text(encoding='utf-8')),ensure_ascii=False,indent=2))"