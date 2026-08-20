// Kiểu dữ liệu dùng chung - khớp với response thật của backend FastAPI (xem src/api/routes/*.py).

export interface ContractSummary {
  contract_id: number;
  name: string;
  source_filename: string;
  n_clauses: number;
}

export type DocStatus = "analyzing" | "analyzed" | "stale";

// Tài liệu trong sidebar - trước khi có contract_id thật (đang upload) chỉ có "file", sau khi
// import xong mới có contract_id (định danh THẬT dùng để so khớp, không dùng "name" vì có thể
// trùng giữa nhiều lần import cùng 1 file).
export interface DocEntry {
  contract_id: number | null;
  name: string;
  source_filename?: string;
  size?: number;
  n_clauses?: number;
  status: DocStatus;
  file: File | null;
  // true CHỈ khi tài liệu vừa được upload trong phiên hiện tại (qua handleUploadFile) - tài liệu
  // tải lại từ danh sách backend lúc mở app (listContracts) là false, dù trạng thái vẫn "analyzed".
  // Dùng để chỉ hiện nhãn "Đã phân tích" cho lần upload thật trong phiên, không hiện cho hợp đồng
  // cũ đã có sẵn từ trước.
  justUploaded?: boolean;
}

export interface Excerpt {
  chunk_index: number;
  text: string;
  score: number | null;
}

// 1 Khoản (Clause) - "score" null nghĩa là không khớp trực tiếp vector search (kéo theo vì lý do
// khác: cùng Điều, quan hệ chéo, preamble...).
export interface ClauseItem {
  number: string;
  title: string;
  article_number: string;
  article_title: string;
  score: number | null;
  text: string;
  excerpts: Excerpt[];
}

// 1 Điều - kết quả retrieval đã gộp Khoản con vào "clauses" (xem
// rag/retrieval/vector_retriever.py::_group_by_article).
export interface ClauseGroup {
  article_number: string;
  article_title: string;
  score: number | null;
  clauses: ClauseItem[];
  text: string;
}

// Cây quan hệ đồ thị đã dẫn từ 1 Clause khớp trực tiếp (root) tới các Clause được kéo theo qua
// REFERS_TO/DEPENDS_ON/EXCEPTION_TO/REFERS_TO_APPENDIX - khớp đúng hình dạng dict thật trả về từ
// rag/context/citation.py::build_evidences (xem schema/evidence.py).
export interface EvidenceNode {
  number: string;
  title: string;
  is_appendix: boolean;
  matched: boolean;
  score: number | null;
  content: string;
  relation?: string; // chỉ node con mới có - loại quan hệ dẫn từ node cha tới nó
  children: EvidenceNode[];
}

export interface Evidence {
  root: EvidenceNode;
  chain: EvidenceNode[];
}

export interface UsageInfo {
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens?: number;
  cost_usd: number | null;
  duration_seconds?: number;
}

// 1 Điều/Khoản dùng làm căn cứ trực tiếp cho kết luận - LLM chỉ trả số hiệu (evidence_clause_numbers,
// tiết kiệm token output), backend tự tra ngược nội dung đầy đủ (xem checklist/evaluator.py::
// resolve_evidence_clauses). Mỗi phần tử hiển thị 1 dòng ở "Căn cứ".
export interface EvidenceClause {
  number: string;
  title: string;
  text: string;
  article_number: string;
  article_title: string;
  is_appendix: boolean;
}

// Điều khoản tương tự nội dung tìm được ở HỢP ĐỒNG KHÁC (vector search, xem GET /api/similar-clauses)
// - dùng để reviewer tham khảo cách viết lại 1 Điều đã bị đánh "Fail".
export interface SimilarClause {
  contract_id: number;
  contract_name: string;
  number: string;
  title: string;
  text: string;
  score: number;
}

export interface SingleAnswer {
  status: string;
  evidence_clauses: EvidenceClause[];
  reasoning: string;
  recommendation: string[]; // mỗi phần tử là 1 ý chỉnh sửa độc lập - xem checklist/models.py::ClauseEvaluation.proposal
  confidence: number;
  verification_units: VerificationUnit[];
  clauses: ClauseGroup[];
  evidences: Evidence[];
  usage: UsageInfo;
}

export interface ChecklistInputItem {
  id: string;
  category: string;
  question: string;
  pass_criteria: string;
  violation_criteria: string;
  note: string;
  severity: string;
  needs_search: boolean;
}

export interface ChecklistInput {
  name: string;
  items: ChecklistInputItem[];
}

// 1 đơn vị xác minh riêng biệt trong pass_criteria/violation_criteria/note - khớp đúng
// checklist/models.py::VerificationUnit.
export interface VerificationUnit {
  requirement: string;
  result: "met" | "not_met" | "not_applicable";
  basis: string;
}

export interface ChecklistEvaluation {
  item_id: string;
  category: string;
  question: string;
  status: "pass" | "fail";
  evidence_clauses: EvidenceClause[];
  reason: string;
  proposal: string;
  confidence: number;
  verification_units: VerificationUnit[];
  cited_clauses: ClauseGroup[];
  evidences: Evidence[];
}

export interface ChecklistReport {
  checklist_name: string;
  evaluations: ChecklistEvaluation[];
}

// Event SSE từ /api/checklist-item/stream - xem services/checklist_service.py::stream_single_item().
export type TraceEvent =
  | { step: "generate_queries"; queries: string[] }
  | { step: "retrieval"; n_clauses: number; articles: { article_number: string; article_title: string }[] }
  | (SingleAnswer & { step: "evaluate" })
  | { step: "error"; message: string };

// Node/edge phẳng của TOÀN BỘ graph 1 hợp đồng - khớp đúng knowledge_graph/graph_export.py
// (khác Evidence[] - vốn chỉ phủ 1 câu hỏi retrieval cụ thể).
export type FullGraphNodeType = "Contract" | "Section" | "Clause" | "Appendix" | "Party" | "GoverningLaw" | "DisputeResolution";

export interface FullGraphNode {
  id: string;
  type: FullGraphNodeType;
  label: string;
  number?: string;
  role?: string;
}

export interface FullGraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface FullGraphResponse {
  contract_id: number;
  contract_name: string;
  nodes: FullGraphNode[];
  edges: FullGraphEdge[];
}

export interface ContextPayload {
  pass_criteria?: string;
  violation_criteria?: string;
  note?: string;
}
