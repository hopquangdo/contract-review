"""Chạy trước bước phân rã (checklist/nodes.py::decompose_requirements) cho TOÀN BỘ checklist, lưu kết quả
ra 1 file JSON - dùng để test riêng retrieval/evaluate (vd Phase 3 hybrid search, đổi ngưỡng...)
nhiều lần mà KHÔNG tốn lại chi phí/thời gian gọi LLM phân rã mỗi lần chạy, vì phần này không đổi
khi chỉ sửa retrieval/evaluate.

Usage: python scripts/dump_requirements.py [--checklist path.json] [--out path.json]
Không truyền gì -> phân rã checklist benchmark mặc định (bm01), ghi vào
data/benchmark/bm01_requirements.json (coi như 1 input CỐ ĐỊNH để test lại, giống ground truth -
khác với data/output/ vốn chỉ chứa kết quả 1 lần chạy pipeline)."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402
from checklist.nodes import decompose_requirements  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_CHECKLIST = Path(__file__).resolve().parent.parent / "data" / "benchmark" / "bm01_checklist_input.json"
_DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "benchmark" / "bm01_requirements.json"


def _dump_one(item: dict, index: int, total: int) -> tuple[str, dict]:
    requirements, usage = decompose_requirements(item)
    logger.info("[%d/%d] %s: phân rã %d yêu cầu", index, total, item["id"], len(requirements))
    return item["id"], {"requirements": requirements, "usage": usage}


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--checklist", default=str(_DEFAULT_CHECKLIST))
    parser.add_argument("--out", default=str(_DEFAULT_OUT))
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args()

    checklist = json.loads(Path(args.checklist).read_text(encoding="utf-8"))
    items = checklist["items"]

    logger.info("Phân rã %d mục checklist '%s'...", len(items), checklist["name"])
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = [executor.submit(_dump_one, item, i, len(items)) for i, item in enumerate(items, start=1)]
        results = dict(f.result() for f in futures)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Đã ghi %d mục vào '%s'.", len(results), out_path)


if __name__ == "__main__":
    main()
