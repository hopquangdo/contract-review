import type { DocEntry } from "../types";

function docKey(doc: { contract_id: number | null; name: string }): string {
  return doc.contract_id != null ? `id:${doc.contract_id}` : `pending:${doc.name}`;
}

interface HeaderProps {
  documents: DocEntry[];
  activeKey: string | null;
  activeDocName: string | null;
  connectionError: string | null;
  onSelectContract: (doc: DocEntry) => void;
  onUploadClick: () => void;
  uploadDisabled: boolean;
  showFullGraph: boolean;
  onToggleFullGraph: () => void;
  hasGraph: boolean;
  onRemoveActiveContract: () => void;
  mockMode: boolean;
  onToggleMock: () => void;
}

export default function Header({
  documents, activeKey, activeDocName, connectionError, onSelectContract, onUploadClick, uploadDisabled,
  showFullGraph, onToggleFullGraph, hasGraph, onRemoveActiveContract, mockMode, onToggleMock,
}: HeaderProps) {
  return (
    <header className="h-[4.5rem] shrink-0 flex items-center gap-4 px-5 border border-border rounded-2xl bg-white">
      <div className="leading-tight shrink-0">
        <div className="font-extrabold text-[0.95rem] text-accent">vAgents Document Review</div>
      </div>

      <div className="w-px h-8 bg-border shrink-0" />

      <div className="min-w-0 flex-1 flex items-center gap-2.5">
        {connectionError ? (
          <span className="text-sm text-fail">{connectionError}</span>
        ) : documents.length === 0 ? (
          <span className="text-sm text-muted">No contracts yet - upload one to get started</span>
        ) : (
          <select
            value={activeKey || ""}
            onChange={(e) => {
              const doc = documents.find((d) => docKey(d) === e.target.value);
              if (doc) onSelectContract(doc);
            }}
            className="font-bold text-[0.95rem] bg-transparent border-none outline-none cursor-pointer max-w-[420px] truncate"
          >
            {documents.map((d) => (
              <option key={docKey(d)} value={docKey(d)}>
                {d.name}
              </option>
            ))}
          </select>
        )}
        {activeDocName && (
          <span className="shrink-0 text-[0.7rem] font-semibold text-ok bg-ok-bg rounded-full px-2.5 py-1">Analyzing</span>
        )}
        {activeKey && (
          <button
            type="button"
            onClick={onRemoveActiveContract}
            title="Remove selected contract"
            className="shrink-0 text-muted hover:text-fail text-base leading-none px-1"
          >
            &times;
          </button>
        )}
      </div>

      <button
        type="button"
        onClick={onToggleMock}
        title="Toggle mock mode - use static sample data instead of calling the real backend/LLM"
        className={`shrink-0 text-[0.72rem] font-bold rounded-lg px-2.5 py-1.5 border ${
          mockMode ? "bg-warn-bg text-warn border-warn/30" : "border-border text-muted hover:bg-black/3"
        }`}
      >
        MOCK {mockMode ? "ON" : "OFF"}
      </button>

      <button
        type="button"
        onClick={onUploadClick}
        disabled={uploadDisabled}
        className="shrink-0 text-[0.8rem] font-semibold border border-border rounded-lg px-3 py-1.5 hover:bg-black/3 disabled:opacity-40"
      >
        + Upload contract
      </button>

      <button
        type="button"
        onClick={onToggleFullGraph}
        disabled={!hasGraph}
        className={`shrink-0 text-[0.8rem] font-semibold rounded-lg px-3 py-1.5 border disabled:opacity-40 disabled:cursor-default ${
          showFullGraph ? "bg-accent text-white border-accent" : "border-accent/30 bg-accent-tint text-accent-dark hover:bg-accent/15"
        }`}
        title="View the full graph of the selected contract"
      >
        {showFullGraph ? "Checklist" : "Full graph"}
      </button>

      <button className="shrink-0 border-none bg-transparent cursor-pointer text-lg text-muted" title="Settings">
        &#9881;
      </button>
    </header>
  );
}
