"""Cấu hình đọc từ biến môi trường - dùng chung cho toàn bộ src/."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# LLM_API_KEY + BASE_URL: đổi 2 biến này là switch được sang nhà cung cấp khác tương thích chuẩn
# OpenAI API (OpenRouter, Azure OpenAI, model tự host qua vLLM/SGLang...) mà không phải sửa code -
# BASE_URL để trống thì dùng thẳng OpenAI chính chủ (https://api.openai.com/v1, do ChatOpenAI tự
# mặc định khi base_url=None). CHỈ áp dụng cho model chat/LLM - embedding vẫn cố định dùng OpenAI
# thật (OPENAI_API_KEY riêng) vì model embedding (text-embedding-3-small) là đặc thù của OpenAI,
# không chắc có sẵn ở nhà cung cấp khác nếu đổi BASE_URL.
LLM_API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("BASE_URL") or None
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or LLM_API_KEY
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
GRAPH_EXTRACTION_MODEL = os.getenv("GRAPH_EXTRACTION_MODEL", "gpt-4.1-mini")
QUERY_GENERATION_MODEL = os.getenv("QUERY_GENERATION_MODEL", "gpt-4.1-mini")
EVALUATOR_MODEL = os.getenv("EVALUATOR_MODEL", "gpt-4.1-mini")
EXCERPT_SPLIT_MODEL = os.getenv("EXCERPT_SPLIT_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
SCORE_GAP_MARGIN = float(os.getenv("SCORE_GAP_MARGIN", "0.012"))
TOP_K_CEILING_PER_QUERY = int(os.getenv("TOP_K_CEILING_PER_QUERY", "3"))
MIN_RETRIEVAL_SCORE = float(os.getenv("MIN_RETRIEVAL_SCORE", "0.62"))

# Rerank bằng cross-encoder model thật (không phải LLM prompt) - tuỳ chọn, mặc định TẮT để không
# đổi hành vi pipeline hiện có. Bật bằng USE_RERANK=true trong env - xem
# rag/retrieval/vector_retriever.py::_search_matching_clauses. Thang điểm rerank (sau sigmoid) khác
# cosine similarity nên cần ngưỡng min_score/gap_margin RIÊNG, không dùng chung với
# MIN_RETRIEVAL_SCORE/SCORE_GAP_MARGIN.
USE_RERANK = os.getenv("USE_RERANK", "false").lower() == "true"
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
RERANK_MIN_SCORE = float(os.getenv("RERANK_MIN_SCORE", "0.3"))
RERANK_GAP_MARGIN = float(os.getenv("RERANK_GAP_MARGIN", "0.1"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Cache kết quả đánh giá checklist ra đĩa (data/cache/) - CHỈ để phát triển frontend không tốn tiền
# gọi lại LLM nhiều lần cho cùng 1 câu hỏi/hợp đồng đã chấm trước đó (xem checklist/eval_cache.py).
# BẬT mặc định vì mục đích hiện tại là dev frontend - tắt bằng CHECKLIST_EVAL_CACHE=false khi cần
# kết quả luôn mới (vd đổi model/prompt rồi muốn thấy ngay, hoặc lên production thật).
CHECKLIST_EVAL_CACHE_ENABLED = os.getenv("CHECKLIST_EVAL_CACHE", "true").lower() == "true"
