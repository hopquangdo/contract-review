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

export interface UsageInfo {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  duration_seconds?: number;
}

export interface SingleAnswer {
  status: string;
  evidence: string;
  reasoning: string;
  recommendation: string;
  confidence: number;
  clauses: ClauseGroup[];
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

export interface ChecklistEvaluation {
  item_id: string;
  category: string;
  question: string;
  status: "pass" | "fail";
  evidence: string;
  reason: string;
  proposal: string;
  cited_clauses: ClauseGroup[];
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

export interface ContextPayload {
  pass_criteria?: string;
  violation_criteria?: string;
  note?: string;
}
