"""Đọc file prompt hệ thống từ llm/prompts/ - dùng chung cho mọi module cần load prompt tĩnh,
tránh lặp lại logic Path(__file__).parent.joinpath(...) ở từng module."""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "llm" / "prompts"


def load_prompt(filename: str) -> str:
    """Đọc nội dung 1 file prompt tĩnh từ llm/prompts/.

    Args:
        filename: Tên file trong llm/prompts/ (vd "checklist_evaluation_system_prompt.txt").

    Returns:
        Nội dung file dạng str (UTF-8).
    """
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
