import { useEffect, useRef, useState } from "react";
import Header from "./components/Header";
import ChecklistPanel from "./components/ChecklistPanel";
import AnalysisPanel from "./components/AnalysisPanel";
import FullGraphView from "./components/FullGraphView";
import UploadPage from "./components/UploadPage";
import { deleteContract, importContract as apiImportContract, isMockMode, listContracts, setMockMode, streamSingleQuestion } from "./api";
import type { ChecklistInput, ChecklistInputItem, DocEntry } from "./types";
import type { ReviewEntry } from "./review";

type RunStatus = "idle" | "running" | "done";

const RUN_CONCURRENCY = 3;

function docKey(doc: { contract_id: number | null; name: string }): string {
  return doc.contract_id != null ? `id:${doc.contract_id}` : `pending:${doc.name}`;
}

async function runWithConcurrency<T>(items: T[], limit: number, worker: (item: T) => Promise<void>): Promise<void> {
  let idx = 0;
  async function next(): Promise<void> {
    const i = idx++;
    if (i >= items.length) return;
    await worker(items[i]);
    return next();
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, () => next()));
}

export default function App() {
  const [documents, setDocuments] = useState<DocEntry[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [activeContractId, setActiveContractId] = useState<number | null>(null);
  const [activeDocName, setActiveDocName] = useState<string | null>(null);
  const [hasGraph, setHasGraph] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const [checklistName, setChecklistName] = useState("");
  const [checklistItems, setChecklistItems] = useState<ChecklistInputItem[]>([]);
  const [entries, setEntries] = useState<ReviewEntry[]>([]);
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [showFullGraph, setShowFullGraph] = useState(false);

  // Trang Upload riêng (chọn file hợp đồng + checklist trước khi phân tích) - mặc định hiện khi
  // chưa có hợp đồng nào đang chọn, hoặc khi người dùng chủ động bấm "+ Upload hợp đồng" ở header.
  const [showUploadPage, setShowUploadPage] = useState(true);
  const [uploadSubmitting, setUploadSubmitting] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const runIdRef = useRef(0);

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
        if (contracts.length) selectContract(docs[docs.length - 1]);
      } catch {
        setConnectionError("Could not connect to the API (http://127.0.0.1:8000)");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Chỉ chạy khi người dùng bấm nút "Phân tích" (xem handleStartAnalysis) hoặc ngay sau khi upload
  // xong ở UploadPage - KHÔNG tự gọi LLM lúc chỉ CHỌN LẠI 1 hợp đồng đã có, để không tốn phí ngoài
  // ý muốn.
  async function runChecklist(contractId: number, items: ChecklistInputItem[]) {
    const runId = ++runIdRef.current;
    setRunStatus("running");
    // Đánh dấu TẤT CẢ mục là "running" NGAY khi bắt đầu - việc backend giới hạn chạy song song
    // tối đa RUN_CONCURRENCY mục cùng lúc là chi tiết nội bộ (ẩn với người dùng), không nên lộ ra
    // UI thành "1 số mục chờ (pending), 1 số mục đang chạy" gây hiểu nhầm là còn xếp hàng thủ công.
    setEntries(items.map((item) => ({ item, status: "running", answer: null, errorMessage: null })));
    setSelectedItemId(items[0]?.id ?? null);

    await runWithConcurrency(items, RUN_CONCURRENCY, async (item) => {
      if (runIdRef.current !== runId) return;
      try {
        let finalAnswer: ReviewEntry["answer"] = null;
        for await (const event of streamSingleQuestion(contractId, item.question, {
          pass_criteria: item.pass_criteria,
          violation_criteria: item.violation_criteria,
          note: item.note,
        })) {
          if (runIdRef.current !== runId) return;
          if (event.step === "evaluate") finalAnswer = event;
          else if (event.step === "error") throw new Error(event.message);
        }
        if (runIdRef.current !== runId) return;
        setEntries((prev) => prev.map((e) => (e.item.id === item.id ? { ...e, status: "done", answer: finalAnswer } : e)));
      } catch (err) {
        if (runIdRef.current !== runId) return;
        setEntries((prev) => prev.map((e) => (e.item.id === item.id ? { ...e, status: "error", errorMessage: (err as Error).message } : e)));
      }
    });
    if (runIdRef.current === runId) setRunStatus("done");
  }

  // Chỉ TẢI danh sách mục checklist mặc định (câu hỏi/tiêu chí) để hiện lên - chưa gọi LLM đánh giá
  // gì cả. Dùng khi CHỌN LẠI 1 hợp đồng đã có sẵn (không đi qua UploadPage nên chưa có checklist
  // do người dùng chọn).
  async function loadDefaultChecklist() {
    runIdRef.current++; // huỷ mọi lượt chạy đang dở của hợp đồng trước đó
    setRunStatus("idle");
    setEntries([]);
    setSelectedItemId(null);
    try {
      const res = await fetch("/checklists/checklist-co-ban.json");
      const data: ChecklistInput = await res.json();
      applyChecklist(data);
    } catch (e) {
      setChecklistName(`Failed to load checklist: ${(e as Error).message}`);
    }
  }

  function applyChecklist(data: ChecklistInput) {
    setChecklistName(data.name);
    setChecklistItems(data.items);
    setEntries(data.items.map((item) => ({ item, status: "pending", answer: null, errorMessage: null })));
  }

  function handleStartAnalysis() {
    if (activeContractId == null || checklistItems.length === 0) return;
    void runChecklist(activeContractId, checklistItems);
  }

  // Phân tích RIÊNG 1 mục checklist (không đợi/không đụng tới các mục khác) - độc lập với runChecklist
  // (chạy CẢ bộ) nên không dùng chung runIdRef/runStatus của lượt chạy hàng loạt, chỉ cập nhật đúng
  // entry của mục này. Cho phép bấm lại dù mục đã "done" (phân tích lại 1 mục cụ thể).
  async function runSingleItem(itemId: string) {
    if (activeContractId == null) return;
    const item = checklistItems.find((i) => i.id === itemId);
    if (!item) return;
    setEntries((prev) => prev.map((e) => (e.item.id === itemId ? { ...e, status: "running", answer: null, errorMessage: null } : e)));
    setSelectedItemId(itemId);
    try {
      let finalAnswer: ReviewEntry["answer"] = null;
      for await (const event of streamSingleQuestion(activeContractId, item.question, {
        pass_criteria: item.pass_criteria,
        violation_criteria: item.violation_criteria,
        note: item.note,
      })) {
        if (event.step === "evaluate") finalAnswer = event;
        else if (event.step === "error") throw new Error(event.message);
      }
      setEntries((prev) => prev.map((e) => (e.item.id === itemId ? { ...e, status: "done", answer: finalAnswer } : e)));
    } catch (err) {
      setEntries((prev) => prev.map((e) => (e.item.id === itemId ? { ...e, status: "error", errorMessage: (err as Error).message } : e)));
    }
  }

  function selectContract(doc: DocEntry) {
    const key = docKey(doc);
    setActiveKey(key);
    setActiveContractId(doc.contract_id);
    setActiveDocName(doc.name);
    setDocuments((docs) => docs.map((d) => ({ ...d, status: docKey(d) === key ? "analyzed" : d.status === "analyzed" ? "stale" : d.status })));
    setHasGraph(true);
    setShowUploadPage(false);
    if (doc.contract_id != null) void loadDefaultChecklist();
  }

  // Luồng UploadPage: import hợp đồng MỚI + checklist người dùng đã chọn (mặc định hoặc tự tải
  // lên), rồi TỰ ĐỘNG chạy phân tích ngay - khớp đúng ý "upload xong là chạy luôn", không cần bấm
  // thêm nút "Phân tích" lần nữa.
  async function handleUploadAndAnalyze(file: File, checklist: ChecklistInput) {
    setUploadSubmitting(true);
    setUploadError(null);
    try {
      const data = await apiImportContract(file);
      setDocuments((docs) => [
        ...docs.map((d) => (d.status === "analyzed" ? { ...d, status: "stale" as const } : d)),
        { contract_id: data.contract_id, name: file.name.replace(/\.[^.]+$/, ""), source_filename: file.name, n_clauses: data.n_clauses, status: "analyzed", file: null, justUploaded: true },
      ]);
      setActiveDocName(file.name.replace(/\.[^.]+$/, ""));
      setActiveKey(docKey({ contract_id: data.contract_id, name: file.name }));
      setActiveContractId(data.contract_id);
      setHasGraph(true);
      setShowUploadPage(false);
      applyChecklist(checklist);
      void runChecklist(data.contract_id, checklist.items);
    } catch (e) {
      setUploadError((e as Error).message);
    } finally {
      setUploadSubmitting(false);
    }
  }

  async function handleRemoveActiveContract() {
    if (activeContractId == null) return;
    const removedId = activeContractId;
    try {
      await deleteContract(removedId);
    } catch (e) {
      setConnectionError(`Failed to remove contract: ${(e as Error).message}`);
      return;
    }
    setDocuments((docs) => docs.filter((d) => d.contract_id !== removedId));
    setActiveKey(null);
    setActiveContractId(null);
    setActiveDocName(null);
    setHasGraph(false);
    setEntries([]);
    setChecklistItems([]);
    setRunStatus("idle");
    setSelectedItemId(null);
    setShowUploadPage(true);
  }

  const selectedEntry = entries.find((e) => e.item.id === selectedItemId) || null;
  const highlightNumbers =
    selectedEntry?.answer?.clauses.flatMap((g) => g.clauses.map((c) => c.number)).filter((n) => n !== "meta") || [];

  return (
    <div className="flex flex-col h-screen bg-bg p-3.5 gap-3.5">
      <Header
        documents={documents}
        activeKey={activeKey}
        activeDocName={activeDocName}
        connectionError={connectionError}
        onSelectContract={selectContract}
        onUploadClick={() => setShowUploadPage(true)}
        uploadDisabled={uploadSubmitting}
        showFullGraph={showFullGraph}
        onToggleFullGraph={() => setShowFullGraph((v) => !v)}
        hasGraph={hasGraph}
        onRemoveActiveContract={handleRemoveActiveContract}
        mockMode={isMockMode()}
        onToggleMock={() => setMockMode(!isMockMode())}
      />

      <div className="flex-1 min-h-0 flex gap-3.5">
        {showUploadPage ? (
          <UploadPage
            onSubmit={handleUploadAndAnalyze}
            submitting={uploadSubmitting}
            submitError={uploadError}
            onCancel={() => setShowUploadPage(false)}
            canCancel={hasGraph}
          />
        ) : (
          <>
            {!showFullGraph && (
              <ChecklistPanel
                checklistName={checklistName}
                entries={entries}
                runStatus={runStatus}
                selectedItemId={selectedItemId}
                onSelectItem={setSelectedItemId}
                onStartAnalysis={handleStartAnalysis}
              />
            )}

            {!hasGraph || activeContractId == null ? (
              <div className="flex-1 min-w-0 flex items-center justify-center border border-border rounded-2xl bg-white text-muted text-sm">
                {connectionError || "No contract selected yet."}
              </div>
            ) : showFullGraph ? (
              <FullGraphView contractId={activeContractId} highlightNumbers={highlightNumbers} onClose={() => setShowFullGraph(false)} />
            ) : (
              <AnalysisPanel
                entry={selectedEntry}
                contractId={activeContractId}
                contractName={activeDocName || ""}
                onAnalyzeItem={runSingleItem}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
