"""Parse file PDF/Word hợp đồng thành Markdown."""

from __future__ import annotations

import io
import logging
import re
import threading
from typing import Callable, Optional

from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode, TableStructureOptions
from docling.datamodel.settings import settings as docling_settings
from docling.document_converter import DocumentConverter, PdfFormatOption

logger = logging.getLogger(__name__)

docling_settings.inference.compile_torch_models = False

_PDF_PIPELINE_OPTIONS = PdfPipelineOptions(
    do_ocr=True,
    do_table_structure=True,
    table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
    do_picture_classification=False,
    do_picture_description=False,
    do_chart_extraction=False,
    do_code_enrichment=False,
    do_formula_enrichment=False,
    generate_page_images=False,
    generate_picture_images=False,
    ocr_batch_size=1,
    layout_batch_size=1,
    table_batch_size=1,
)

_PIPELINE_LOG_RE = re.compile(r"PIPELINE_PROFILING Stage (?P<stage>\S+): run_id=\d+ pages=\[(?P<pages>[^\]]*)\]")
_PDF_PIPELINE_LOGGER_NAME = "docling.pipeline.standard_pdf_pipeline"

ProgressCallback = Callable[[str, list[int]], None]

CONTRACT_EXTENSIONS = (".pdf", ".docx", ".doc")


class _PageProgressLogHandler(logging.Handler):
    """Suy ra tiến độ xử lý theo từng trang từ log nội bộ của pipeline docling."""

    def __init__(self, on_progress: ProgressCallback):
        super().__init__(level=logging.DEBUG)
        self._on_progress = on_progress

    def emit(self, record: logging.LogRecord) -> None:
        match = _PIPELINE_LOG_RE.search(record.getMessage())
        if not match:
            return
        pages = [int(p) for p in match.group("pages").split(",") if p.strip()]
        if pages:
            self._on_progress(match.group("stage"), pages)


class DoclingParser:
    """Chuyển file hợp đồng gốc (PDF/Word, kể cả bản scan) thành Markdown có cấu trúc."""

    def __init__(self) -> None:
        self._converter: Optional[DocumentConverter] = None
        self._lock = threading.Lock()

    def _get_converter(self) -> DocumentConverter:
        if self._converter is None:
            with self._lock:
                if self._converter is None:
                    self._converter = DocumentConverter(
                        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=_PDF_PIPELINE_OPTIONS)}
                    )
        return self._converter

    def parse_to_markdown(self, name: str, data: bytes, on_progress: ProgressCallback | None = None) -> str:
        """Chuyển nội dung file (bytes) thành Markdown. `on_progress(stage, pages)` được gọi
        mỗi khi docling xử lý xong 1 batch trang (chỉ áp dụng cho PDF) - dùng để UI hiển thị
        tiến độ."""
        logger.info("Bắt đầu parse tài liệu bằng docling, name=%s, size_bytes=%d", name, len(data))
        stream = DocumentStream(name=name, stream=io.BytesIO(data))

        pipeline_logger = logging.getLogger(_PDF_PIPELINE_LOGGER_NAME)
        previous_level = pipeline_logger.level
        handler: _PageProgressLogHandler | None = None
        if on_progress is not None:
            handler = _PageProgressLogHandler(on_progress)
            pipeline_logger.addHandler(handler)
            pipeline_logger.setLevel(logging.DEBUG)

        try:
            result = self._get_converter().convert(stream)
        except Exception:
            logger.exception("Lỗi khi parse tài liệu bằng docling, name=%s", name)
            raise
        finally:
            if handler is not None:
                pipeline_logger.removeHandler(handler)
                pipeline_logger.setLevel(previous_level)

        markdown = result.document.export_to_markdown()
        logger.info("Hoàn tất parse tài liệu bằng docling, name=%s, markdown_len=%d", name, len(markdown))
        return markdown


_default_parser: DoclingParser | None = None


def get_parser() -> DoclingParser:
    """Trả về instance DoclingParser dùng chung (singleton) cho toàn ứng dụng."""
    global _default_parser
    if _default_parser is None:
        _default_parser = DoclingParser()
    return _default_parser


def parse_to_markdown(name: str, data: bytes, on_progress: ProgressCallback | None = None) -> str:
    """Hàm tiện ích: gọi parse_to_markdown trên instance DoclingParser dùng chung, sau đó
    chuẩn hoá khoảng trắng thừa (xem text_cleanup.normalize_markdown)."""
    from ingestion.text_cleanup import normalize_markdown

    raw = get_parser().parse_to_markdown(name, data, on_progress=on_progress)
    return normalize_markdown(raw)
