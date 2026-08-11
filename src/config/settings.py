"""Cấu hình đọc từ biến môi trường - dùng chung cho toàn bộ src/."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
CHAT_MODEL = os.getenv("EVALUATOR_MODEL", "gpt-4.1-mini")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
SCORE_GAP_MARGIN = float(os.getenv("SCORE_GAP_MARGIN", "0.012"))
TOP_K_CEILING_PER_QUERY = int(os.getenv("TOP_K_CEILING_PER_QUERY", "3"))
MIN_RETRIEVAL_SCORE = float(os.getenv("MIN_RETRIEVAL_SCORE", "0.62"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
