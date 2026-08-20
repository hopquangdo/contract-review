"""Lắp LangGraph cho luồng chấm 1 mục checklist: generate_queries -> retrieve -> rerank -> expand ->
build_context -> evaluate.

Mỗi node là 1 hàm run_<tên node> trong checklist/nodes.py (xem schema/checklist_item_state.py
cho state dùng chung) - thêm node mới chỉ cần viết thêm 1 hàm run_<tên> trong nodes.py rồi nối vào
graph ở đây, không phải sửa các node đã có. Bước retrieval (trước đây gộp chung 1 node) đã tách
thành 4 node riêng (retrieve/rerank/expand/build_context) để mỗi bước có thể thay/kiểm thử độc lập -
xem rag/retrieval.py::Retrieval cho logic thật của từng bước."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from checklist import nodes
from schema.checklist_item_state import ChecklistItemState


def build_item_graph():
    """Lắp và compile LangGraph cho luồng chấm 1 mục checklist - trả về graph đã compile, dùng
    `.invoke(...)`/`.stream(...)` như trước (xem checklist/evaluator.py::ChecklistEvaluator cho nơi
    gọi, giữ 1 instance ở __init__ để không compile lại mỗi lần chấm)."""
    graph = StateGraph(ChecklistItemState)
    graph.add_node("generate_queries", nodes.run_generate_queries)
    graph.add_node("retrieve", nodes.run_retrieve)
    graph.add_node("rerank", nodes.run_rerank)
    graph.add_node("expand", nodes.run_expand)
    graph.add_node("build_context", nodes.run_build_context)
    graph.add_node("evaluate", nodes.run_evaluate)
    graph.set_entry_point("generate_queries")
    graph.add_edge("generate_queries", "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "expand")
    graph.add_edge("expand", "build_context")
    graph.add_edge("build_context", "evaluate")
    graph.add_edge("evaluate", END)
    return graph.compile()
