import type { DocEntry } from "../types";

function docKey(doc: DocEntry): string {
  return doc.contract_id != null ? `id:${doc.contract_id}` : `pending:${doc.name}`;
}

function fileExtLabel(name: string): string {
  // Trả "" (không phải "?") khi không tách được đuôi file - hợp đồng build qua script/notebook
  // (không qua API import) có thể không có source_filename, không nên hiện placeholder gây khó hiểu.
  const m = /\.([a-zA-Z0-9]+)$/.exec(name || "");
  return m ? m[1].toUpperCase() : "";
}

function fileSizeLabel(bytes?: number): string {
  // "size" CHỈ có cho file vừa chọn trong phiên này (đối tượng File JS) - GET /api/contracts
  // không trả field này (Neo4j không lưu kích thước file), nên hợp đồng tải lại từ backend sẽ
  // luôn thiếu, không phải bug.
  if (bytes === undefined || bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusLabel(doc: DocEntry): string {
  if (doc.status === "analyzing") return "Đang phân tích...";
  // "Đã phân tích" chỉ hiện cho tài liệu VỪA upload trong phiên hiện tại - hợp đồng tải lại từ
  // danh sách backend lúc mở app không hiện nhãn này dù đang active.
  if (doc.status === "analyzed" && doc.justUploaded) return "Đã phân tích";
  if (doc.status === "analyzed") return "";
  return "Chưa chọn lại";
}

interface SidebarProps {
  documents: DocEntry[];
  activeKey: string | null;
  onUploadClick: () => void;
  onSelect: (doc: DocEntry) => void;
  onRemove: (key: string) => void;
  uploadDisabled: boolean;
  importStatus: { kind: "ok" | "warn" | "err"; text: string } | null;
}

export default function Sidebar({ documents, activeKey, onUploadClick, onSelect, onRemove, uploadDisabled, importStatus }: SidebarProps) {
  const statusColor = { ok: "bg-ok-bg text-ok", warn: "bg-warn-bg text-warn", err: "bg-fail-bg text-fail" };

  return (
    <aside className="w-60 shrink-0 flex flex-col border border-border rounded-2xl bg-white overflow-hidden">
      <div className="h-[4.5rem] shrink-0 px-4 flex items-center border-b border-border">
        <h3 className="text-xs uppercase tracking-wider text-muted m-0">Documents</h3>
      </div>

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
        <input id="contract-file-input" type="file" accept=".pdf,.docx,.doc" className="hidden" />
        <button
          onClick={onUploadClick}
          disabled={uploadDisabled}
          className="w-full border-[1.5px] border-dashed border-border rounded-xl py-3.5 px-2.5 flex flex-col items-center gap-1 text-sm font-semibold hover:border-accent hover:bg-accent-tint transition-colors disabled:opacity-50"
        >
          <span className="w-[1.7rem] h-[1.7rem] rounded-full bg-accent-tint text-accent flex items-center justify-center text-lg font-bold">+</span>
          <span>Upload hợp đồng</span>
        </button>

        {importStatus && (
          <div className={`text-xs px-2.5 py-2 rounded-lg leading-snug ${statusColor[importStatus.kind]}`}>{importStatus.text}</div>
        )}

        <div className="flex flex-col gap-1.5">
          {documents.length === 0 && <div className="text-muted text-sm text-center py-4 px-2">Chưa import hợp đồng nào.</div>}
          {documents.map((doc) => {
            const key = docKey(doc);
            const active = key === activeKey;
            const subParts = [fileExtLabel(doc.source_filename || doc.name), fileSizeLabel(doc.size), statusLabel(doc)].filter(Boolean);
            // Hợp đồng không có source_filename/size (vd build qua script, không qua API import)
            // sẽ có subParts rỗng hoàn toàn - dùng n_clauses (luôn có từ backend) làm dự phòng để
            // dòng phụ không bao giờ trống trơn.
            if (subParts.length === 0 && doc.n_clauses !== undefined) subParts.push(`${doc.n_clauses} Điều`);
            const sub = subParts.join(" · ");
            return (
              <div
                key={key}
                onClick={() => !active && onSelect(doc)}
                className={`flex items-start gap-2 px-2.5 py-2 rounded-[10px] cursor-pointer text-sm border ${
                  active ? "bg-accent-tint border-accent/20" : "border-transparent hover:bg-black/3"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <div className="font-semibold break-words">{doc.name}</div>
                  <div className={`text-xs mt-0.5 ${active ? "text-ok" : "text-muted"}`}>{sub}</div>
                </div>
                {!active && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemove(key);
                    }}
                    className="shrink-0 text-muted hover:text-fail text-base leading-none p-0.5"
                    title="Xoá khỏi danh sách"
                  >
                    &times;
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
