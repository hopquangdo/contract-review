"""Benchmark CHỈ retrieval (không gọi LLM evaluate) - đo recall/precision của
rag.retrieval.Retrieval.run() trên bộ (query, expected_evidences) độc
lập với checklist, cho MỌI hợp đồng liệt kê trong data/benchmark/retrieval/ground_truth.json.

Mỗi mục ground truth chỉ có "query" (câu tìm kiếm tự viết) + "expected_evidences" (cây quan hệ đồ
thị ĐÚNG, cùng hình dạng root/chain/children với evidences thật - xem
rag/retrieval.py::Retrieval.run) - KHÔNG qua bước LLM phân rã
(decompose_requirements) nên kết quả TẤT ĐỊNH (không nhiễu non-determinism), rẻ và nhanh - phù hợp
chạy lại sau MỖI lần sửa code retrieval. Số hiệu trong "expected_evidences" đã ở ĐÚNG định dạng nội
bộ hệ thống ("14"/"PL03"/"PL03.5", không phải "Điều 14"/"Phụ lục 03") nên so khớp trực tiếp, không
cần chuẩn hoá.

Usage: python scripts/benchmark_retrieval.py [--ground-truth path.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.logging_config import setup_logging  # noqa: E402
from knowledge_graph.client import get_graph  # noqa: E402
from rag.retrieval import Retrieval  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_GROUND_TRUTH = Path(__file__).resolve().parent.parent / "data" / "benchmark" / "retrieval" / "ground_truth.json"
_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "output"


def flatten_expected_numbers(expected_evidences: list[dict]) -> set[str]:
    """Trả về tập TOÀN BỘ số hiệu Clause xuất hiện trong cây expected_evidences (root + mọi node
    con đệ quy, mọi cây trong danh sách) - đây là tập "đáp án đúng" phẳng dùng để tính recall/
    precision, không quan tâm hình dạng cây (hình dạng chỉ dùng để đối chiếu quan hệ đồ thị riêng)."""
    numbers: set[str] = set()

    def walk(node: dict) -> None:
        numbers.add(node["number"])
        for child in node.get("children", []):
            walk(child)

    for tree in expected_evidences:
        walk(tree["root"])
        for child in tree["chain"]:
            walk(child)
    return numbers


def predicted_identifiers(groups: list[dict]) -> set[str]:
    """Tập số hiệu hệ thống đã truy hồi, gồm CẢ cấp Điều/Phụ lục gốc (article_number của mỗi
    group) LẪN cấp Khoản/sub-clause cụ thể bên trong (number của từng clause con) - so khớp được
    với ground truth dù trích dẫn ở mức nào (chỉ nêu chung "PL03" hay nêu rõ "PL03.3")."""
    ids: set[str] = set()
    for g in groups:
        ids.add(g["article_number"])
        for c in g["clauses"]:
            ids.add(c["number"])
    return ids


def _retrieval_metrics(groups: list[dict], expected_evidences: list[dict]) -> dict:
    relevant = flatten_expected_numbers(expected_evidences)
    predicted = predicted_identifiers(groups)
    if not relevant:
        return {"recall": None, "precision": None, "hit": []}
    hit = relevant & predicted
    recall = len(hit) / len(relevant)
    precision = len(hit) / len(predicted) if predicted else 0.0
    return {"recall": round(recall, 3), "precision": round(precision, 3), "hit": sorted(hit), "missed": sorted(relevant - hit)}


def _total_contract_clauses(contract_id: int) -> int:
    """Tổng số Clause THẬT của 1 hợp đồng (không tính preamble) - dùng làm mẫu số tính % hợp đồng
    bị kéo vào 1 lần retrieval (xem "pct_of_contract" trong _expansion_stats)."""
    rows = get_graph().query(
        "MATCH (c:Clause {agreement_id: $cid}) WHERE coalesce(c.is_preamble, false) = false RETURN count(c) AS n",
        params={"cid": contract_id},
    )
    return rows[0]["n"]


def _expansion_stats(result: dict, total_contract_clauses: int) -> dict:
    """Đo mức độ "kéo theo" của 1 lần retrieval: n_matched (= số root trong evidences), n_clauses
    (tổng số Khoản trả về, KHÔNG tính preamble/metadata vì 2 group này luôn đính kèm mọi lần gọi,
    không phải "kéo theo" qua quan hệ), expansion_ratio = n_clauses / n_matched (trung bình 1 Khoản
    khớp trực tiếp kéo theo bao nhiêu Khoản khác), và pct_of_contract = n_clauses / tổng số Khoản
    THẬT của hợp đồng."""
    n_matched = len(result["evidences"])
    n_clauses = sum(len(g["clauses"]) for g in result["clauses"] if g["article_number"] not in ("0", "meta"))
    return {
        "n_matched": n_matched,
        "n_clauses": n_clauses,
        "expansion_ratio": round(n_clauses / n_matched, 2) if n_matched else None,
        "total_contract_clauses": total_contract_clauses,
        "pct_of_contract": round(100 * n_clauses / total_contract_clauses, 1) if total_contract_clauses else None,
    }


def run_one_benchmark(name: str, contract_id: int, items: list[dict]) -> dict:
    total_contract_clauses = _total_contract_clauses(contract_id)
    rows = []
    for item in items:
        result = Retrieval(contract_id).run([item["query"]])
        metrics = _retrieval_metrics(result["clauses"], item["expected_evidences"])
        expansion = _expansion_stats(result, total_contract_clauses)
        rows.append({
            "query": item["query"],
            "expected_evidences": item["expected_evidences"],
            **metrics,
            **expansion,
            # OUTPUT THẬT của model - KHÔNG cắt/rút gọn - để soi trực tiếp model sai ở đâu, không
            # chỉ nhìn recall/precision/hit/missed (số liệu tổng hợp không đủ để debug).
            "actual_clauses": result["clauses"],
            "actual_evidences": result["evidences"],
        })
        logger.info(
            "[%s] '%s' -> recall=%s precision=%s (thiếu: %s) | n_matched=%d n_clauses=%d (%.1f%% hợp đồng) "
            "expansion_ratio=%s",
            name, item["query"], metrics["recall"], metrics["precision"], metrics.get("missed") or "-",
            expansion["n_matched"], expansion["n_clauses"], expansion["pct_of_contract"], expansion["expansion_ratio"],
        )

    scored = [r for r in rows if r["recall"] is not None]
    mean_recall = sum(r["recall"] for r in scored) / len(scored) if scored else None
    mean_precision = sum(r["precision"] for r in scored) / len(scored) if scored else None
    ratios = [r["expansion_ratio"] for r in rows if r["expansion_ratio"] is not None]
    pcts = [r["pct_of_contract"] for r in rows if r["pct_of_contract"] is not None]
    return {
        "name": name,
        "contract_id": contract_id,
        "n_items": len(items),
        "total_contract_clauses": total_contract_clauses,
        "mean_recall": round(mean_recall, 3) if mean_recall is not None else None,
        "mean_precision": round(mean_precision, 3) if mean_precision is not None else None,
        "mean_n_matched": round(statistics.mean(r["n_matched"] for r in rows), 2),
        "mean_n_clauses": round(statistics.mean(r["n_clauses"] for r in rows), 2),
        "mean_expansion_ratio": round(statistics.mean(ratios), 2) if ratios else None,
        "median_expansion_ratio": round(statistics.median(ratios), 2) if ratios else None,
        "min_expansion_ratio": round(min(ratios), 2) if ratios else None,
        "max_expansion_ratio": round(max(ratios), 2) if ratios else None,
        "mean_pct_of_contract": round(statistics.mean(pcts), 1) if pcts else None,
        "median_pct_of_contract": round(statistics.median(pcts), 1) if pcts else None,
        "min_pct_of_contract": round(min(pcts), 1) if pcts else None,
        "max_pct_of_contract": round(max(pcts), 1) if pcts else None,
        "items": rows,
    }


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", default=str(_DEFAULT_GROUND_TRUTH))
    args = parser.parse_args()

    data = json.loads(Path(args.ground_truth).read_text(encoding="utf-8"))

    results = []
    for entry in data["benchmarks"]:
        logger.info("===== Benchmark '%s' (contract_id=%s) =====", entry["name"], entry["contract_id"])
        results.append(run_one_benchmark(entry["name"], entry["contract_id"], entry["items"]))

    logger.info("\n===== TỔNG HỢP =====")
    logger.info(
        "Chú thích: Khớp = số Khoản khớp TRỰC TIẾP vector search (= số root trong evidences). "
        "Trả Về = TỔNG số Khoản hệ thống trả về cho LLM (Khớp + Khoản kéo theo qua quan hệ đồ thị, "
        "KHÔNG tính preamble/metadata). Tỷ Lệ Kéo Theo = Trả Về / Khớp (1 Khoản khớp trực tiếp kéo "
        "theo trung bình bao nhiêu Khoản khác). % Hợp Đồng = Trả Về / Tổng số Khoản THẬT của hợp "
        "đồng (bao nhiêu phần trăm hợp đồng bị kéo vào 1 lần truy hồi)."
    )
    header = (
        f"{'Benchmark':15} {'ContractID':10} {'TotalClauses':13} {'N Items':8} {'Recall':8} {'Precision':10} "
        f"{'Khớp(avg)':10} {'TrảVề(avg)':11} "
        f"{'TyLeKeoTheo avg':16}{'median':9}{'min':7}{'max':7} "
        f"{'PhanTramHopDong avg':20}{'median':9}{'min':7}{'max':7}"
    )
    logger.info(header)
    logger.info("-" * len(header))
    for r in results:
        logger.info(
            "%-15s %-10s %-13s %-8d %-8s %-10s %-10s %-11s "
            "%-16s%-9s%-7s%-7s "
            "%-20s%-9s%-7s%-7s",
            r["name"], r["contract_id"], r["total_contract_clauses"], r["n_items"], r["mean_recall"],
            r["mean_precision"], r["mean_n_matched"], r["mean_n_clauses"],
            r["mean_expansion_ratio"], r["median_expansion_ratio"], r["min_expansion_ratio"], r["max_expansion_ratio"],
            f"{r['mean_pct_of_contract']}%", f"{r['median_pct_of_contract']}%", f"{r['min_pct_of_contract']}%",
            f"{r['max_pct_of_contract']}%",
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = _OUTPUT_DIR / "retrieval"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"retrieval_benchmark_{timestamp}.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Đã ghi chi tiết (JSON, đủ actual_clauses/actual_evidences) vào '%s'.", json_path)


if __name__ == "__main__":
    main()
