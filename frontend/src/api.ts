import type { ChecklistInput, ChecklistReport, ContextPayload, ContractSummary, TraceEvent } from "./types";

export const API_BASE = "http://127.0.0.1:8000";

export async function listContracts(): Promise<ContractSummary[]> {
  const res = await fetch(`${API_BASE}/api/contracts`);
  const data = await res.json();
  return data.contracts || [];
}

export async function importContract(file: File): Promise<ContractSummary & { n_cross: number }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/contracts`, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
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
