import { useEffect, useRef, useState } from "react";
import Sidebar from "./components/Sidebar";
import InputBar from "./components/InputBar";
import ContextRow from "./components/ContextRow";
import EvidencePanel from "./components/EvidencePanel";
import TraceMessage, { type TraceStep } from "./components/TraceMessage";
import ChecklistReportView from "./components/ChecklistReportView";
import { deleteContract, importContract as apiImportContract, listContracts, streamSingleQuestion, submitChecklist } from "./api";
import type { ChecklistEvaluation, ChecklistInput, ChecklistReport, ClauseGroup, DocEntry, SingleAnswer } from "./types";

type ChatMessage =
  | { kind: "user"; id: string; text: string }
  | { kind: "trace"; id: string; steps: TraceStep[]; answer: SingleAnswer | null; error: string | null; done: boolean }
  | { kind: "checklist"; id: string; report: ChecklistReport | null; total: number }
  | { kind: "invalid-file"; id: string; filename: string };

function docKey(doc: { contract_id: number | null; name: string }): string {
  return doc.contract_id != null ? `id:${doc.contract_id}` : `pending:${doc.name}`;
}

let seq = 0;
const nextId = () => `m${seq++}`;

export default function App() {
  const [documents, setDocuments] = useState<DocEntry[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [activeContractId, setActiveContractId] = useState<number | null>(null);
  const [activeDocName, setActiveDocName] = useState<string | null>(null);
  const [hasGraph, setHasGraph] = useState(false);
  const [importStatus, setImportStatus] = useState<{ kind: "ok" | "warn" | "err"; text: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [ctxPass, setCtxPass] = useState("");
  const [ctxViolation, setCtxViolation] = useState("");
  const [ctxNote, setCtxNote] = useState("");
  const [attachedFile, setAttachedFile] = useState<File | null>(null);

  const [evidenceGroups, setEvidenceGroups] = useState<ClauseGroup[] | null>(null);
  const [evidenceMsgId, setEvidenceMsgId] = useState<string | null>(null);

  const contractFileInputRef = useRef<HTMLInputElement>(null);
  const messageScrollRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      if (messageScrollRef.current) messageScrollRef.current.scrollTop = messageScrollRef.current.scrollHeight;
    });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Tải danh sách hợp đồng đã có lúc mở app, tự chọn hợp đồng gần nhất.
  useEffect(() => {
    (async () => {
      try {
        const contracts = await listContracts();
        const docs: DocEntry[] = contracts.map((c) => ({
          contract_id: c.contract_id,
          name: c.name,
          source_filename: c.source_filename,
          n_clauses: c.n_clauses,
          status: "stale",
          file: null,
        }));
        setDocuments(docs);
        if (contracts.length) {
          selectContract(docs[docs.length - 1]);
        }
      } catch {
        setConnectionError("Không kết nối được API (http://127.0.0.1:8000)");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectContract(doc: DocEntry) {
    const key = docKey(doc);
    setActiveKey(key);
    setActiveContractId(doc.contract_id);
    setActiveDocName(doc.name);
    setDocuments((docs) => docs.map((d) => ({ ...d, status: docKey(d) === key ? "analyzed" : d.status === "analyzed" ? "stale" : d.status })));
    setHasGraph(true);
    setMessages([]);
    setEvidenceGroups(null);
    setEvidenceMsgId(null);
  }

  async function handleUploadFile(file: File) {
    const pendingKey = docKey({ contract_id: null, name: file.name });
    setDocuments((docs) => {
      const marked = docs.map((d) => (d.status === "analyzed" ? { ...d, status: "stale" as const } : d));
      if (!marked.some((d) => d.file === file)) {
        return [...marked, { contract_id: null, name: file.name, size: file.size, status: "analyzing", file }];
      }
      return marked;
    });
    // Không hiện banner "Đang phân tích..." ở đây - trạng thái này đã hiện ngay dưới tên tài liệu
    // trong danh sách (xem Sidebar::statusLabel), banner riêng chỉ dư thừa. Chỉ báo khi XONG/LỖI.
    setImportStatus(null);
    setUploading(true);
    try {
      const data = await apiImportContract(file);
      setDocuments((docs) =>
        docs.map((d) => (d.file === file ? { ...d, contract_id: data.contract_id, n_clauses: data.n_clauses, status: "analyzed", justUploaded: true } : d))
      );
      setActiveDocName(file.name);
      setActiveKey(docKey({ contract_id: data.contract_id, name: file.name }));
      setActiveContractId(data.contract_id);
      setImportStatus({ kind: "ok", text: `Xong: ${data.n_clauses} Điều, ${data.n_cross} quan hệ chéo.` });
      setHasGraph(true);
      setMessages([]);
      setEvidenceGroups(null);
      setEvidenceMsgId(null);
    } catch (e) {
      setDocuments((docs) => docs.map((d) => (d.file === file ? { ...d, status: "stale" } : d)));
      setImportStatus({ kind: "err", text: `Lỗi import: ${(e as Error).message}` });
    } finally {
      setUploading(false);
      void pendingKey;
    }
  }

  async function removeDoc(key: string) {
    const doc = documents.find((d) => docKey(d) === key);
    if (!doc) return;
    // Tài liệu chưa có contract_id (đang pending upload, chưa import xong) chỉ tồn tại ở
    // frontend - không có gì để gọi API xoá, bỏ khỏi danh sách cục bộ là đủ.
    if (doc.contract_id == null) {
      setDocuments((docs) => docs.filter((d) => docKey(d) !== key));
      return;
    }
    try {
      await deleteContract(doc.contract_id);
      setDocuments((docs) => docs.filter((d) => docKey(d) !== key));
    } catch (e) {
      setImportStatus({ kind: "err", text: `Lỗi khi xoá hợp đồng: ${(e as Error).message}` });
    }
  }

  function showEvidence(msgId: string, groups: ClauseGroup[]) {
    setEvidenceMsgId(msgId);
    setEvidenceGroups(groups);
  }

  async function handleSend() {
    if (!hasGraph) return;
    const text = question.trim();
    const file = attachedFile;
    if (!text && !file) return;

    setQuestion("");
    setAttachedFile(null);

    if (file) {
      let checklistData: ChecklistInput;
      try {
        checklistData = JSON.parse(await file.text());
      } catch {
        const id = nextId();
        setMessages((m) => [...m, { kind: "user", id: nextId(), text: `Đính kèm checklist: ${file.name}` }, { kind: "invalid-file", id, filename: file.name }]);
        return;
      }
      const userId = nextId();
      const reportId = nextId();
      setMessages((m) => [
        ...m,
        { kind: "user", id: userId, text: `Đính kèm checklist: ${checklistData.name} (${checklistData.items.length} mục)` },
        { kind: "checklist", id: reportId, report: null, total: checklistData.items.length },
      ]);
      try {
        const report = await submitChecklist(activeContractId!, checklistData);
        setMessages((m) => m.map((msg) => (msg.id === reportId ? { ...msg, report } : msg)));
        if (report.evaluations.length) showEvidence(reportId, report.evaluations[0].cited_clauses);
      } catch (e) {
        setMessages((m) =>
          m.map((msg) => (msg.id === reportId ? { kind: "invalid-file", id: reportId, filename: `Lỗi khi gọi API: ${(e as Error).message}` } : msg))
        );
      }
      return;
    }

    // Giữ nguyên 3 ô tiêu chí sau khi gửi (không xoá) - hữu ích khi hỏi liên tiếp nhiều câu dùng
    // chung 1 bộ tiêu chí (vd rà nhiều khía cạnh của cùng 1 điều khoản). Chỉ lưu trong state React
    // (mất khi tải lại trang), không lưu localStorage/backend.
    const ctx = { pass_criteria: ctxPass.trim() || undefined, violation_criteria: ctxViolation.trim() || undefined, note: ctxNote.trim() || undefined };

    const traceId = nextId();
    setMessages((m) => [...m, { kind: "user", id: nextId(), text }, { kind: "trace", id: traceId, steps: [], answer: null, error: null, done: false }]);

    try {
      for await (const event of streamSingleQuestion(activeContractId!, text, ctx)) {
        if (event.step === "generate_queries") {
          setMessages((m) => m.map((msg) => (msg.id === traceId && msg.kind === "trace" ? { ...msg, steps: [...msg.steps, event] } : msg)));
        } else if (event.step === "retrieval") {
          setMessages((m) => m.map((msg) => (msg.id === traceId && msg.kind === "trace" ? { ...msg, steps: [...msg.steps, event] } : msg)));
        } else if (event.step === "evaluate") {
          setMessages((m) => m.map((msg) => (msg.id === traceId && msg.kind === "trace" ? { ...msg, answer: event, done: true } : msg)));
          showEvidence(traceId, event.clauses);
        } else if (event.step === "error") {
          setMessages((m) => m.map((msg) => (msg.id === traceId && msg.kind === "trace" ? { ...msg, error: event.message, done: true } : msg)));
        }
      }
    } catch (e) {
      setMessages((m) => m.map((msg) => (msg.id === traceId && msg.kind === "trace" ? { ...msg, error: `Lỗi khi gọi API: ${(e as Error).message}`, done: true } : msg)));
    }
  }

  return (
    <div className="flex items-stretch h-screen bg-bg p-3.5 gap-3.5">
      <Sidebar
        documents={documents}
        activeKey={activeKey}
        onUploadClick={() => contractFileInputRef.current?.click()}
        onSelect={(doc) => (doc.contract_id != null ? selectContract(doc) : doc.file && handleUploadFile(doc.file))}
        onRemove={removeDoc}
        uploadDisabled={uploading}
        importStatus={importStatus}
      />
      <input
        ref={contractFileInputRef}
        type="file"
        accept=".pdf,.docx,.doc"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleUploadFile(f);
          e.target.value = "";
        }}
      />

      <main className="flex-1 min-w-0 flex flex-col border border-border rounded-2xl bg-white overflow-hidden">
        <div className="h-[4.5rem] shrink-0 px-[1.1rem] flex flex-col justify-center border-b border-border">
          <div className="flex items-center gap-2.5">
            <span className="font-extrabold text-[1.02rem] text-accent">Contract AI</span>
            <button className="ml-auto border-none bg-transparent cursor-pointer text-lg text-muted" title="Cài đặt">
              &#9881;
            </button>
          </div>
          <div className="text-[0.8rem] text-muted mt-0.5">
            {connectionError || (activeDocName ? `Hợp đồng: ${activeDocName}` : "Chưa có hợp đồng nào được import")}
          </div>
        </div>

        <div ref={messageScrollRef} className="flex-1 overflow-y-auto flex flex-col items-center px-4 pt-5 pb-4 bg-bg">
          <div className="w-full max-w-[700px] flex flex-col gap-3.5">
            {messages.map((msg) => {
              if (msg.kind === "user") {
                return (
                  <div key={msg.id} className="flex flex-col gap-1">
                    <span className="text-[0.78rem] text-muted font-semibold px-0.5 self-end">Bạn</span>
                    <div className="max-w-[78%] self-end rounded-2xl px-[1.1rem] py-[0.85rem] bg-accent-tint">
                      <p className="m-0 text-[0.94rem] leading-relaxed">{msg.text}</p>
                    </div>
                  </div>
                );
              }
              if (msg.kind === "trace") {
                return (
                  <div key={msg.id} className="flex flex-col gap-1">
                    <span className="text-[0.78rem] text-muted font-semibold px-0.5">Contract AI</span>
                    <TraceMessage
                      steps={msg.steps}
                      answer={msg.answer}
                      error={msg.error}
                      done={msg.done}
                      evidenceActive={evidenceMsgId === msg.id}
                      onShowEvidence={() => msg.answer && showEvidence(msg.id, msg.answer.clauses)}
                    />
                  </div>
                );
              }
              if (msg.kind === "checklist") {
                return (
                  <div key={msg.id} className="flex flex-col gap-1">
                    <span className="text-[0.78rem] text-muted font-semibold px-0.5">Contract AI</span>
                    {msg.report ? (
                      <ChecklistReportView report={msg.report} onShowEvidence={(clauses: ChecklistEvaluation["cited_clauses"]) => showEvidence(msg.id, clauses)} />
                    ) : (
                      <div className="rounded-2xl border border-border bg-white p-4 text-sm flex items-center">
                        <span className="spinner" />
                        Đang chấm {msg.total} mục...
                      </div>
                    )}
                  </div>
                );
              }
              return (
                <div key={msg.id} className="flex flex-col gap-1">
                  <span className="text-[0.78rem] text-muted font-semibold px-0.5">Contract AI</span>
                  <div className="rounded-2xl border border-border bg-white p-4 text-sm">
                    <p className="m-0">File JSON không hợp lệ.</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <InputBar
          value={question}
          onChange={setQuestion}
          onSend={handleSend}
          onAttach={setAttachedFile}
          attachedFile={attachedFile}
          onRemoveAttached={() => setAttachedFile(null)}
          disabled={!hasGraph}
        >
          <ContextRow pass={ctxPass} violation={ctxViolation} note={ctxNote} onPassChange={setCtxPass} onViolationChange={setCtxViolation} onNoteChange={setCtxNote} />
        </InputBar>
      </main>

      <EvidencePanel groups={evidenceGroups} />
    </div>
  );
}
