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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402
from config.settings import SCORE_GAP_MARGIN, TOP_K_CEILING_PER_QUERY  # noqa: E402
from checklist.evaluator import ChecklistEvaluator  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_CHECKLIST = Path(__file__).resolve().parent.parent / "data" / "benchmark" / "bm01_checklist_input.json"
_evaluator = ChecklistEvaluator()


def process_one_item(contract_id: int, item: dict, index: int, total: int, requirements_map: dict | None = None) -> dict:
    # run_retrieval_pipeline() trả về danh sách ĐIỀU đã gộp (mỗi phần tử có article_number/
    # article_title/score/clauses con), không phải danh sách Khoản phẳng - xem
    # rag/retrieval/vector_retriever.py::_group_by_article().
    # requirements_map: nếu có (từ scripts/dump_requirements.py), BỎ QUA bước phân rã LLM, dùng
    # requirements đã lưu sẵn - tiện test riêng retrieval/evaluate mà không tốn gọi lại phân rã.
    if requirements_map and item["id"] in requirements_map:
        requirements = requirements_map[item["id"]]["requirements"]
        evaluation, clauses, _evidences, _usage = _evaluator.evaluate_checklist_item_with_requirements(contract_id, item, requirements)
    else:
        evaluation, clauses, _evidences, _usage = _evaluator.evaluate_checklist_item(contract_id, item)
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
        # Chép lại nguyên văn tiêu chí đầu vào (không tốn thêm lệnh LLM, item đã có sẵn) - để báo
        # cáo/UI xem output hiển thị được cạnh nhau tiêu chí VÀ kết luận, không phải tra ngược lại
        # file checklist gốc.
        "pass_criteria": item.get("pass_criteria", ""),
        "violation_criteria": item.get("violation_criteria", ""),
        "note": item.get("note", ""),
        "status": evaluation.status,
        "evidence_clause_numbers": evaluation.evidence_clause_numbers,
        "reason": evaluation.reason,
        "proposal": evaluation.proposal,
        # Giữ nguyên cấu trúc group (article_number/article_title/score/clauses con) thay vì tự
        # dựng lại 1 phần - tránh lệch schema mỗi khi run_retrieval_pipeline() đổi cấu trúc trả
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
        help="Đường dẫn ghi báo cáo JSON - mặc định data/output/contract{id}_system_output.json, "
        "GHI ĐÈ lần chạy trước (chỉ giữ 1 bản mới nhất, không tích luỹ file theo ngày-giờ).",
    )
    parser.add_argument(
        "--requirements", default=None,
        help="File JSON đã phân rã sẵn (từ scripts/dump_requirements.py) - nếu truyền, BỎ QUA bước "
        "phân rã LLM cho các item có trong file, dùng thẳng requirements đã lưu (tiện test riêng "
        "retrieval/evaluate nhiều lần không tốn gọi lại phân rã).",
    )
    args = parser.parse_args()

    checklist = json.loads(Path(args.checklist).read_text(encoding="utf-8"))
    items = checklist["items"]
    requirements_map = json.loads(Path(args.requirements).read_text(encoding="utf-8")) if args.requirements else None
    logger.info(
        "Đánh giá contract_id=%s theo checklist '%s' (%d mục)%s, truy hồi adaptive top-k mỗi truy vấn con "
        "(gap_margin=%.2f, trần %d Khoản/truy vấn)...",
        args.contract_id,
        checklist["name"],
        len(items),
        f" (dùng requirements đã lưu sẵn từ '{args.requirements}')" if requirements_map else "",
        SCORE_GAP_MARGIN,
        TOP_K_CEILING_PER_QUERY,
    )

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(process_one_item, args.contract_id, item, i, len(items), requirements_map): item
            for i, item in enumerate(items, start=1)
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    report = {"checklist_name": checklist["name"], "contract_id": args.contract_id, "evaluations": results}
    report_json = json.dumps(report, ensure_ascii=False, indent=2)

    out_path = Path(args.out) if args.out else (
        Path(__file__).resolve().parent.parent / "data" / "output" / f"contract{args.contract_id}_system_output.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_json, encoding="utf-8")
    logger.info("Đã ghi báo cáo vào '%s'.", out_path)


if __name__ == "__main__":
    main()
