"""Công cụ dòng lệnh để chấm 1 checklist trên graph tri thức của 1 hợp đồng.

Usage: python scripts/evaluate_checklist.py [--checklist path.json] [--contract-id 1] [--out report.json]
Không truyền gì cả -> chạy thẳng checklist benchmark mặc định (bm01) trên contract_id=1, tiện bấm
"Run" trong IDE mà không cần gõ tham số.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402
from config.settings import SCORE_GAP_MARGIN, TOP_K_CEILING_PER_QUERY  # noqa: E402
from rag.checklist_graph import evaluate_checklist_item  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_CHECKLIST = Path(__file__).resolve().parent.parent / "data" / "benchmark" / "bm01_checklist_input.json"


def process_one_item(contract_id: int, item: dict, index: int, total: int) -> dict:
    # retrieve_relevant_clauses() trả về danh sách ĐIỀU đã gộp (mỗi phần tử có article_number/
    # article_title/score/clauses con), không phải danh sách Khoản phẳng - xem
    # rag/retrieval/vector_retriever.py::_group_by_article().
    evaluation, clauses, _usage = evaluate_checklist_item(contract_id, item)
    logger.info(
        "[%d/%d] %s: truy hồi %d Điều liên quan nhất (%s) -> %s",
        index,
        total,
        item["id"],
        len(clauses),
        ", ".join("Đ" + g["article_number"] for g in clauses),
        evaluation.status.upper(),
    )
    return {
        "item_id": item["id"],
        "category": item["category"],
        "question": item["question"],
        "status": evaluation.status,
        "evidence": evaluation.evidence,
        "reason": evaluation.reason,
        "proposal": evaluation.proposal,
        # Giữ nguyên cấu trúc group (article_number/article_title/score/clauses con) thay vì tự
        # dựng lại 1 phần - tránh lệch schema mỗi khi retrieve_relevant_clauses() đổi cấu trúc trả
        # về (đã từng là bug: script này giả định "clauses" phẳng trong khi đã đổi sang gộp Điều).
        "cited_clauses": clauses,
    }


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--checklist", default=str(_DEFAULT_CHECKLIST), help="Path to checklist .json (deep_check format)")
    parser.add_argument("--contract-id", type=int, default=1)
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument(
        "--out", default=None,
        help="Thư mục/đường dẫn ghi báo cáo JSON - mặc định tự đặt tên có hậu tố ngày-giờ trong data/output/, "
        "tránh ghi đè lần chạy trước. Nếu truyền đường dẫn cụ thể, hậu tố ngày-giờ vẫn được chèn trước phần đuôi file.",
    )
    args = parser.parse_args()

    checklist = json.loads(Path(args.checklist).read_text(encoding="utf-8"))
    items = checklist["items"]
    logger.info(
        "Đánh giá contract_id=%s theo checklist '%s' (%d mục), truy hồi adaptive top-k mỗi truy vấn con "
        "(gap_margin=%.2f, trần %d Khoản/truy vấn)...",
        args.contract_id,
        checklist["name"],
        len(items),
        SCORE_GAP_MARGIN,
        TOP_K_CEILING_PER_QUERY,
    )

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(process_one_item, args.contract_id, item, i, len(items)): item
            for i, item in enumerate(items, start=1)
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    report = {"checklist_name": checklist["name"], "contract_id": args.contract_id, "evaluations": results}
    report_json = json.dumps(report, ensure_ascii=False, indent=2)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.out:
        base = Path(args.out)
        out_path = base.with_stem(f"{base.stem}_{timestamp}")
    else:
        out_path = Path(__file__).resolve().parent.parent / "data" / "output" / f"contract{args.contract_id}_system_output_{timestamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_json, encoding="utf-8")
    logger.info("Đã ghi báo cáo vào '%s'.", out_path)


if __name__ == "__main__":
    main()
