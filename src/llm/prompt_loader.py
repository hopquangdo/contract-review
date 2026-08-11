"""Đọc file prompt hệ thống từ llm/prompts/ - dùng chung cho mọi module cần load prompt tĩnh,
tránh lặp lại logic Path(__file__).parent.joinpath(...) ở từng module."""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(filename: str) -> str:
    """filename: tên file trong llm/prompts/ (vd "checklist_evaluation_system_prompt.txt")."""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
