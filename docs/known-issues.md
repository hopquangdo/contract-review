# Vấn đề còn tồn đọng - Retrieval / Graph / Prompt

Ghi lại tại thời điểm 2026-08-11, sau phiên tối ưu recall/accuracy cho pipeline chấm checklist
(xem `data/output/eval_report_*.json` gần nhất để biết số đo cụ thể: accuracy ~0.765, recall
~0.971, precision ~0.185 - đo từ 1 lần chạy, xem mục "Nhiễu hệ thống" bên dưới).

## 1. Tầng Retrieval

**Đã giải quyết trong phiên này:**
- Trần top-K toàn cục gộp mọi truy vấn (khái niệm nhiều bị khái niệm ít chiếm chỗ) → đổi sang
  adaptive top-k theo độ mạnh (gần điểm hạng 1) + độ đa dạng (khác Điều) cho từng truy vấn riêng
  (xem `rag/retrieval/vector_retriever.py::_select_query_candidates`).
- Khoảng cách từ vựng (SLA, nhà thầu phụ...) → nguyên tắc tổng quát sinh truy vấn diễn giải song
  song truy vấn nguyên văn (xem `llm/prompts/query_generation_prompt.txt`).

**Còn tồn đọng:**
- **Chỉ có 1 kênh tìm kiếm (vector/embedding)** - không có kênh fulltext/keyword dự phòng. Mọi
  trường hợp khớp lệch từ vựng tinh vi hơn (số hiệu Điều nhắc chéo, tên riêng, con số cụ thể như
  "12 giờ", "99,9%") phụ thuộc hoàn toàn vào embedding có "nhớ" đúng hay không. Giới hạn kiến trúc,
  không phải chuyện tuning prompt/threshold sửa được. (Kiến trúc "Vector + Fulltext → RRF" đã bàn ở
  đầu phiên làm việc nhưng chưa triển khai.)
- **`expand_by_relations()` phụ thuộc từ khóa tiếng Việt cứng** (`_RELATION_KEYWORDS` trong
  `rag/retrieval/expansion.py`) - chỉ kéo thêm quan hệ REFERS_TO/DEPENDS_ON/EXCEPTION_TO khi câu
  hỏi chứa đúng từ như "ngoại lệ", "trừ khi", "theo quy định tại". Heuristic mỏng, dễ bỏ sót nếu
  câu hỏi diễn đạt cùng ý bằng từ khác.
- **`SCORE_GAP_MARGIN=0.012` là số tinh chỉnh qua vài lần thử trên đúng 1 bộ benchmark (bm01)**,
  chưa có cơ sở lý thuyết vững. Hợp đồng/checklist khác có thể có phân bố điểm cosine khác hẳn,
  khiến ngưỡng này không còn phù hợp - rủi ro overfit vào 1 bộ dữ liệu.
- **Precision rất thấp (~0.15-0.2)** - retrieval thiên hẳn về recall, đánh đổi lấy rất nhiều nhiễu
  (12-15 Điều/mục, phần lớn không liên quan) đưa thẳng vào evaluate. Không có bước lọc lại nào sau
  khi truy hồi.

## 2. Tầng Graph (schema/extraction)

- **Chất lượng quan hệ trích xuất (REFERS_TO/DEPENDS_ON/EXCEPTION_TO/DEFINES) chưa được kiểm chứng
  độc lập.** Mọi cải thiện retrieval trong phiên này giả định các quan hệ đã trích đúng từ
  `llm/graph_extraction.py`, nhưng chưa đo được % quan hệ trích đúng. Nếu extraction bỏ sót quan
  hệ, `expand_by_relations`/`expand_by_definitions` sẽ không kéo được gì dù logic retrieval đúng.
- **`GET_SIBLING_CLAUSE_NUMBERS` (expand_to_full_article) kéo TOÀN BỘ Khoản của 1 Điều** mỗi khi có
  1 Khoản khớp - hợp lý cho Điều ngắn, nhưng với hợp đồng có Điều rất dài (nhiều Khoản) có thể làm
  phình ngữ cảnh tương tự vấn đề "quá nhiều Điều" đã thấy ở tầng truy vấn - chưa kiểm tra với hợp
  đồng dài hơn bm01.
- **Không có cơ chế versioning/incremental update graph** khi hợp đồng được re-upload/sửa - ngoài
  phạm vi phiên này nhưng đáng lưu ý khi sắp có thêm nhiều hợp đồng khác.

## 3. Tầng Prompt (query generation + evaluation)

### `query_generation_prompt.txt`
Nguyên tắc "1 truy vấn nguyên văn + 1 truy vấn diễn giải" đã tổng quát hóa tốt (không few-shot gắn
với hợp đồng cụ thể), nhưng thực nghiệm cho thấy model không tuân theo đều tay 100% - vd với từ
"SLA" vẫn thỉnh thoảng không được diễn giải dù đã siết prompt 4 lần liên tiếp. Giới hạn cố hữu của
prompt-only steering, không có gì đảm bảo tuyệt đối.

### `checklist_evaluation_system_prompt.txt`
- `verification_units` đã ép cấu trúc xác minh từng điều kiện, sửa đúng lỗi dạng "bỏ sót điều kiện
  con" (quan sát ở CL-01/CL-05/CL-12) - nhưng vẫn thấy hiện tượng **gộp nhầm 2 điều kiện vào 1
  unit** ở 1 số lần chạy, dù đã có quy tắc "1-1, không gộp" rõ ràng - enforcement bằng văn bản vẫn
  không tuyệt đối.
- **Quy tắc "not_applicable" cho điều kiện có điều kiện** (vd "nếu có yếu tố nước ngoài thì...")
  chưa hoạt động đúng khi cần suy luận GIÁN TIẾP (hợp đồng thuần nội địa → suy ra không có yếu tố
  nước ngoài) thay vì có 1 câu khẳng định trực tiếp "không có yếu tố nước ngoài". Model có xu
  hướng đánh "not_met" (an toàn nhưng sai) thay vì "not_applicable" trong trường hợp này.
- **`status` do LLM tự viết có thể mâu thuẫn với chính `verification_units` nó vừa liệt kê** - đã
  quan sát 1 trường hợp cụ thể (verification_units đúng nhưng status flip sai). Lỗ hổng này có thể
  vá HOÀN TOÀN bằng code (tính `status` từ `verification_units` thay vì tin field tự do LLM viết ra
  - không tốn thêm chi phí LLM) - đã đề xuất, CHƯA triển khai.
- **Không có unit test/regression test tự động cho prompt** - mỗi lần sửa phải chạy tay benchmark
  17 mục để biết có regression hay không, không có gì chặn 1 lần sửa "tưởng đúng" nhưng vô tình phá
  hỏng case khác (đã xảy ra 2 lần trong phiên này).

## 4. Nhiễu hệ thống (cross-cutting)

- **Non-determinism**: `temperature=0` không tuyệt đối deterministic (đã chứng minh trực tiếp bằng
  cách gọi lặp lại cùng 1 input, ra kết quả hơi khác nhau giữa các lần). Mọi con số accuracy/
  recall/precision đo được trong phiên này đều từ **1 lần chạy duy nhất mỗi cấu hình** - chưa có
  phép đo lặp lại (n≥3, lấy trung bình + độ lệch chuẩn) để tách bạch "thay đổi thật" khỏi "nhiễu
  ngẫu nhiên giữa 2 lần chạy". Đây là rủi ro lớn nhất về mặt phương pháp luận của toàn bộ quá trình
  tối ưu trong phiên - nhiều kết luận "tốt hơn"/"tệ hơn" chỉ dựa trên 1 mẫu quan sát.

## Đề xuất tiếp theo (chưa triển khai, xếp theo chi phí/lợi ích)

1. **Tính `status` từ `verification_units` bằng code** - rẻ nhất, an toàn nhất, không tốn thêm chi
   phí LLM, vá đúng 1 lớp lỗi đã quan sát được.
2. **Hybrid search (Vector + Fulltext qua RRF)** - tác động recall trực tiếp nhất, nhưng cần thêm
   fulltext index và hiệu chỉnh lại ngưỡng điểm từ đầu (thang RRF khác thang cosine).
3. **Thêm bước lọc liên quan (relevance filter) sau retrieval, trước evaluate** - tác động precision
   trực tiếp nhất, đổi lại thêm 1 lệnh LLM/mục checklist (tăng cost/latency).
4. **Chạy benchmark lặp lại nhiều lần (n≥3) lấy trung bình** - không cải thiện điểm số, nhưng cần
   thiết để các kết luận "tốt hơn/tệ hơn" trong tương lai đáng tin cậy hơn.
