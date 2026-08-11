# Changelog

Tóm tắt các đợt thay đổi lớn, theo thứ tự thời gian - mỗi mục ghi lý do đổi và trạng thái hiện tại sau khi đổi.

## Refactor schema graph (Excerpt, is_preamble, taxonomy, constraint)

**Lý do:** review kiến trúc graph cho thấy 6 vấn đề: `Excerpt`/`HAS_EXCERPT` được document nhưng chưa implement, `Clause` số "0" đè ngữ nghĩa lên trường `number`, `ClauseType` tự do không kiểm soát (LLM sinh nhãn khác nhau mỗi lần build), `CREATE` (không phải `MERGE`) khiến dữ liệu phụ thuộc hoàn toàn vào việc luôn gọi `clear_graph()`, regex tách Section/Clause chỉ hiểu tiếng Việt không có fallback, LLM có thể tham chiếu tới số Điều không tồn tại.

**Đã đổi:**
- `src/graph/schema_migration.py` (mới) - constraint `UNIQUE` trên `uid` cho Clause/Excerpt/Definition/ClauseType/Organization/GoverningLaw/DisputeResolution (Neo4j Community không hỗ trợ `NODE KEY` composite nên dùng property gộp sẵn thay vì nhiều property).
- `src/graph/builder.py` - `Clause`/`Definition` đổi từ `CREATE` sang `MERGE` theo `uid`; thêm `Excerpt` node thật (`Clause -[:HAS_EXCERPT]-> Excerpt`), vector index chuyển từ `Clause.embedding` sang `Excerpt.embedding`; thêm `is_preamble: boolean` trên Clause thay cho việc dựa vào số hiệu `"0"`.
- `src/domain/clause_taxonomy.py` (mới) - 14 loại điều khoản cố định, ép qua `Literal` trong `ClauseRelations.clause_type` (Pydantic) + cập nhật prompt LLM tương ứng.
- `src/ingestion/section_splitter.py` - thử tuần tự nhiều pattern (PHẦN/CHƯƠNG/PART, ĐIỀU/MỤC/ARTICLE) thay vì 1 regex cố định, fallback về 1 Section/1 Clause nếu không pattern nào khớp.
- `src/llm/graph_extraction.py` - lọc `refers_to`/`depends_on`/`exception_to` theo danh sách số hiệu Điều có thật sau khi LLM trả về (loại tham chiếu ảo giác).
- `src/retrieval/vector_retriever.py` - truy vấn qua `Excerpt.embedding` + `WHERE is_preamble = true/false` thay vì `Clause.embedding` + so sánh số `"0"`.

**Trạng thái hiện tại:** build lại 2 lần liên tiếp cho cùng 1 hợp đồng không nhân đôi node; ClauseType giảm từ 20 nhãn tự do xuống còn tối đa 14 nhãn cố định.

## Đổi pathway embedding

**Lý do:** ingestion dùng `genai.vector.encode` (hàm Cypher của Neo4j, đã bị đánh dấu deprecated, cảnh báo mỗi lần build) trong khi retrieval dùng `OpenAIEmbeddings` (LangChain, client-side) - 2 pathway khác nhau cho cùng 1 việc, dễ lệch cấu hình (model/dimensions phải đồng bộ thủ công).

**Đã thử:** model tiếng Việt `dangvantuan/vietnamese-embedding` (sentence-transformers, chạy local) - gặp lỗi thật: model chỉ hỗ trợ tối đa ~258 token dù tài liệu ghi 512, cần thêm bước cắt bớt. Theo yêu cầu, đã **quay lại OpenAI** nhưng giữ lại kiến trúc có thể đổi provider dễ dàng.

**Đã đổi:**
- `src/llm/embeddings.py` (mới) - `EmbeddingProvider` (interface trừu tượng) + `OpenAIEmbeddingProvider` (implementation đang dùng). Đổi provider sau này chỉ cần viết thêm 1 class implement interface, không sửa nơi gọi.
- `src/graph/builder.py` - bỏ hẳn `genai.vector.encode`, tính embedding client-side qua `get_embeddings().embed_texts(...)` rồi `SET` thẳng vào `Excerpt.embedding`.
- `src/llm/client.py` - xoá `get_embeddings_model()`/`OpenAIEmbeddings` (không còn dùng, tránh 2 pathway song song).

**Trạng thái hiện tại:** không còn cảnh báo deprecated khi build; 1 pipeline embedding duy nhất cho cả ingestion lẫn retrieval.

## Multi-contract: Neo4j lưu nhiều hợp đồng cùng lúc, không liên kết nhau

**Lý do:** trước đây hệ thống chỉ lưu ĐÚNG 1 hợp đồng, mỗi lần import gọi `clear_graph()` xoá sạch. Muốn lưu nhiều hợp đồng song song và truy vấn được qua API.

**Đã đổi:**
- `src/graph/builder.py` - `Organization`/`GoverningLaw`/`DisputeResolution`/`ClauseType` (trước đây merge theo tên trần, dùng chung mọi hợp đồng) giờ mang `uid` có tiền tố `contract_id`, đảm bảo 2 hợp đồng khác nhau không tự động gộp node dù trùng tên đối tác/loại điều khoản. Thêm `next_contract_id()` (số hợp đồng tự tăng) và `delete_contract(contract_id)` (xoá riêng 1 hợp đồng). `clear_graph()` không còn được gọi tự động khi import - chỉ còn là công cụ dọn dẹp thủ công.
- `src/graph/schema_migration.py` - constraint cũ (`clausetype_name`, `org_name` - unique theo tên trần) bị `DROP`, thay bằng constraint theo `uid`.
- `scripts/build_graph.py` - bỏ `clear_graph()` tự động, `--contract-id` giờ optional (mặc định tự tăng).

**Đã kiểm chứng:** build cùng 1 nội dung 2 lần (trường hợp trùng tên khó nhất) - mỗi node (Organization, ClauseType...) tạo đúng 2 bản ghi độc lập theo `agreement_id`, không gộp.

## Tách service layer + route API cho multi-contract

**Lý do:** route trước đây (`api/main.py`) vừa lo HTTP vừa chứa logic nghiệp vụ; và cần API mới để liệt kê/lấy/xoá hợp đồng theo `contract_id` thay vì hằng số cố định `CONTRACT_ID = 1`.

**Đã đổi:**
- `src/services/contract_service.py`, `src/services/checklist_service.py` (mới) - toàn bộ nghiệp vụ (parse, build graph, gọi LLM, tổng hợp kết quả) chuyển vào đây.
- `src/api/routes/contracts.py`, `src/api/routes/checklist.py` - route giờ chỉ lo đọc file/tham số HTTP và mã lỗi, gọi thẳng qua service.
- API đổi từ `/api/status`, `/api/import` (single-tenant) sang `/api/contracts` (GET danh sách, POST thêm mới), `/api/contracts/{id}` (GET 1 hợp đồng, DELETE xoá riêng). `/api/checklist-item` và `/api/checklist` giờ bắt buộc kèm `contract_id`.

**main.py chuyển ra cùng cấp với `src/`** - chạy bằng `uvicorn main:app` từ thư mục gốc thay vì `cd src && uvicorn api.main:app`.

**Chưa làm - cần lưu ý:** `frontend/app.js` vẫn gọi API kiểu cũ (`/api/status`, `/api/import` không tham số, `/api/checklist-item` không có `contract_id`) - sẽ lỗi cho tới khi được sửa lại để có UI chọn hợp đồng đang làm việc.

## Docstring

Thêm docstring 1 câu, mô tả đúng mục đích (không lặp tên, không chi tiết cài đặt) cho toàn bộ class trong `src/` và toàn bộ file `.py` (kể cả các `__init__.py` trước đây rỗng).
