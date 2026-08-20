import type { ChecklistInput, ChecklistReport, ContextPayload, ContractSummary, FullGraphResponse, SimilarClause, TraceEvent } from "./types";

export const API_BASE = "http://127.0.0.1:8000";

// Chế độ MOCK - đọc dữ liệu tĩnh trong public/mock/ (đã lấy từ 1 lượt gọi API THẬT, xem
// frontend/public/mock/*.json) THAY VÌ gọi backend/LLM thật - dùng khi chỉ đang chỉnh sửa giao diện,
// không cần dữ liệu mới, để không tốn tiền/thời gian gọi lại LLM. Mặc định lấy từ .env.local
// (VITE_MOCK=true, KHÔNG commit file này) - nhưng có thể BẬT/TẮT ngay trên Header lúc chạy (xem
// isMockMode/setMockMode) mà không cần sửa .env.local + khởi động lại dev server, lưu lại qua
// localStorage nên vẫn nhớ lựa chọn sau khi tải lại trang.
const MOCK_STORAGE_KEY = "vagents_mock_override";

export function isMockMode(): boolean {
  const override = localStorage.getItem(MOCK_STORAGE_KEY);
  if (override === "true") return true;
  if (override === "false") return false;
  return import.meta.env.VITE_MOCK === "true";
}

// Đổi chế độ MOCK rồi tải lại trang - đơn giản hơn nhiều so với đồng bộ lại toàn bộ state (hợp đồng/
// checklist đang chọn) giữa 2 nguồn dữ liệu KHÁC NHAU (mock tĩnh vs backend thật) giữa chừng.
export function setMockMode(value: boolean): void {
  localStorage.setItem(MOCK_STORAGE_KEY, String(value));
  window.location.reload();
}

if (isMockMode()) console.warn("[MOCK MODE] Đang dùng dữ liệu tĩnh trong public/mock/, KHÔNG gọi backend/LLM thật.");

async function loadMock<T>(path: string): Promise<T> {
  const res = await fetch(`/mock/${path}`);
  return res.json();
}

export async function listContracts(): Promise<ContractSummary[]> {
  if (isMockMode()) return (await loadMock<{ contracts: ContractSummary[] }>("contracts.json")).contracts;
  const res = await fetch(`${API_BASE}/api/contracts`);
  const data = await res.json();
  return data.contracts || [];
}

export async function importContract(file: File): Promise<ContractSummary & { n_cross: number }> {
  if (isMockMode()) {
    const contracts = await loadMock<{ contracts: (ContractSummary & { n_cross?: number })[] }>("contracts.json");
    const c = contracts.contracts[0];
    return { ...c, name: file.name.replace(/\.[^.]+$/, ""), n_cross: c.n_cross ?? 0 };
  }
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/contracts`, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function getContractGraph(contractId: number): Promise<FullGraphResponse> {
  // Mỗi hợp đồng có 1 file graph riêng (đã ghi lại từ /api/contracts/{id}/graph THẬT, xem
  // frontend/public/mock/graph-{contractId}.json) - không dùng chung 1 file cho mọi hợp đồng nữa,
  // để chọn được nhiều hợp đồng khác nhau trong dropdown lúc dev ở MOCK mode.
  if (isMockMode()) return loadMock<FullGraphResponse>(`graph-${contractId}.json`);
  const res = await fetch(`${API_BASE}/api/contracts/${contractId}/graph`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// Tìm Điều khoản tương tự nội dung ở CÁC HỢP ĐỒNG KHÁC (vector search, không gọi LLM) - dùng ở tab
// "References" để reviewer tham khảo cách viết lại 1 Điều đã bị đánh "Fail" (xem GET
// /api/similar-clauses, services/checklist_service.py::get_similar_clauses).
export async function getSimilarClauses(
  contractId: number,
  clauseNumber: string,
  topK = 5,
  sameTypeOnly = true,
): Promise<SimilarClause[]> {
  if (isMockMode()) {
    // Map THẬT (ghi lại từ các lượt gọi thật) số hiệu Điều -> kết quả, RIÊNG cho từng hợp đồng (xem
    // similar-clauses-{contractId}.json) - số hiệu lạ (không nằm trong bộ đã ghi, vd checklist tuỳ
    // chỉnh) rơi về similar-clauses.json (1 kết quả mẫu chung) làm fallback.
    const byNumber = await loadMock<Record<string, SimilarClause[]>>(`similar-clauses-${contractId}.json`).catch(
      () => ({}) as Record<string, SimilarClause[]>,
    );
    if (clauseNumber in byNumber) return byNumber[clauseNumber];
    return (await loadMock<{ clauses: SimilarClause[] }>("similar-clauses.json")).clauses;
  }
  const params = new URLSearchParams({
    contract_id: String(contractId),
    clause_number: clauseNumber,
    top_k: String(topK),
    same_type_only: String(sameTypeOnly),
  });
  const res = await fetch(`${API_BASE}/api/similar-clauses?${params}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return (await res.json()).clauses || [];
}

export async function deleteContract(contractId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/contracts/${contractId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
}

export async function submitChecklist(contractId: number, checklistData: ChecklistInput): Promise<ChecklistReport> {
  const blob = new Blob([JSON.stringify(checklistData)], { type: "application/json" });
  const formData = new FormData();
  formData.append("file", blob, "checklist.json");
  formData.append("contract_id", String(contractId));
  const res = await fetch(`${API_BASE}/api/checklist`, { method: "POST", body: formData });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Đọc SSE (Server-Sent Events) từ /api/checklist-item/stream - phát ra từng bước
// (generate_queries/retrieval/evaluate) NGAY khi backend xong, không đợi cả pipeline.
export async function* streamSingleQuestion(
  contractId: number,
  question: string,
  ctx: ContextPayload,
  signal?: AbortSignal
): AsyncGenerator<TraceEvent> {
  if (isMockMode()) {
    // Bộ sự kiện THẬT (ghi lại từ các lượt gọi LLM thật cho từng mục checklist mặc định, RIÊNG cho
    // từng hợp đồng - xem checklist-answers-{contractId}.json) tra theo đúng nội dung câu hỏi - mỗi
    // mục có kết quả riêng thay vì dùng chung 1 bộ. Câu hỏi lạ (checklist tuỳ chỉnh không nằm trong
    // bộ đã ghi, hoặc hợp đồng chưa có file riêng) rơi về stream-events.json (1 bộ mẫu chung) làm
    // fallback.
    const answers = await loadMock<Record<string, TraceEvent[]>>(`checklist-answers-${contractId}.json`).catch(
      () => ({}) as Record<string, TraceEvent[]>,
    );
    const events = answers[question] || (await loadMock<TraceEvent[]>("stream-events.json"));
    for (const e of events) {
      await new Promise((r) => setTimeout(r, 400)); // giả lập độ trễ để thấy rõ trạng thái "Đang chấm..."
      yield e;
    }
    return;
  }
  const res = await fetch(`${API_BASE}/api/checklist-item/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contract_id: contractId, question, ...ctx }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sepIdx: number;
    while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sepIdx);
      buffer = buffer.slice(sepIdx + 2);
      const dataLine = rawEvent.split("\n").find((l) => l.startsWith("data:"));
      if (!dataLine) continue;
      yield JSON.parse(dataLine.slice(5).trim()) as TraceEvent;
    }
  }
}
