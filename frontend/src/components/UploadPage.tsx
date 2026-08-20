import { useRef, useState } from "react";
import type { ChecklistInput } from "../types";

const DEFAULT_CHECKLIST_URL = "/checklists/checklist-co-ban.json";
const DEFAULT_CHECKLIST_LABEL = "Basic contract analysis checklist";

type ChecklistSource = "default" | "custom";

interface UploadPageProps {
  onSubmit: (contractFile: File, checklist: ChecklistInput) => void;
  submitting: boolean;
  submitError: string | null;
  onCancel: () => void;
  canCancel: boolean;
}

export default function UploadPage({ onSubmit, submitting, submitError, onCancel, canCancel }: UploadPageProps) {
  const [contractFile, setContractFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [checklistSource, setChecklistSource] = useState<ChecklistSource>("default");
  const [customChecklist, setCustomChecklist] = useState<ChecklistInput | null>(null);
  const [customChecklistError, setCustomChecklistError] = useState<string | null>(null);
  const [loadingDefault, setLoadingDefault] = useState(false);
  const [defaultChecklistMeta, setDefaultChecklistMeta] = useState<{ name: string; n: number } | null>(null);

  const contractInputRef = useRef<HTMLInputElement>(null);
  const checklistInputRef = useRef<HTMLInputElement>(null);

  function pickContractFile(f: File) {
    setContractFile(f);
  }

  async function pickChecklistFile(f: File) {
    setCustomChecklistError(null);
    try {
      const data: ChecklistInput = JSON.parse(await f.text());
      if (!data.name || !Array.isArray(data.items)) throw new Error("JSON file is missing 'name' or 'items'.");
      setCustomChecklist(data);
    } catch (e) {
      setCustomChecklist(null);
      setCustomChecklistError(`Invalid checklist file: ${(e as Error).message}`);
    }
  }

  async function handleStart() {
    if (!contractFile) return;
    if (checklistSource === "custom") {
      if (!customChecklist) return;
      onSubmit(contractFile, customChecklist);
      return;
    }
    setLoadingDefault(true);
    try {
      const res = await fetch(DEFAULT_CHECKLIST_URL);
      const data: ChecklistInput = await res.json();
      setDefaultChecklistMeta({ name: data.name, n: data.items.length });
      onSubmit(contractFile, data);
    } catch (e) {
      setCustomChecklistError(`Could not load the default checklist: ${(e as Error).message}`);
    } finally {
      setLoadingDefault(false);
    }
  }

  const canStart = !!contractFile && (checklistSource === "default" || !!customChecklist) && !submitting && !loadingDefault;

  return (
    <div className="flex-1 min-w-0 flex items-center justify-center border border-border rounded-2xl bg-white overflow-y-auto p-6">
      <div className="w-full max-w-xl flex flex-col gap-5">
        <div>
          <h2 className="text-lg font-bold m-0">Upload contract</h2>
          <p className="text-sm text-muted m-0 mt-1">Choose the contract file and the checklist to use for automatic analysis.</p>
        </div>

        {/* Step 1: pick contract file */}
        <div>
          <div className="text-[0.72rem] font-bold uppercase tracking-wide text-muted mb-1.5">1. Contract</div>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragActive(false);
              const f = e.dataTransfer.files?.[0];
              if (f) pickContractFile(f);
            }}
            onClick={() => contractInputRef.current?.click()}
            className={`cursor-pointer border-2 border-dashed rounded-xl px-4 py-8 flex flex-col items-center gap-2 text-center transition-colors ${
              dragActive ? "border-accent bg-accent-tint" : "border-border hover:border-accent/50"
            }`}
          >
            <span className="w-10 h-10 rounded-full bg-accent-tint text-accent flex items-center justify-center text-xl font-bold">+</span>
            {contractFile ? (
              <span className="text-sm font-semibold">{contractFile.name}</span>
            ) : (
              <>
                <span className="text-sm font-semibold">Drag & drop a file here, or click to choose</span>
                <span className="text-[0.76rem] text-muted">Supports .pdf, .docx, .doc, .md, .txt</span>
              </>
            )}
          </div>
          <input
            ref={contractInputRef}
            type="file"
            accept=".pdf,.docx,.doc,.md,.txt"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) pickContractFile(f);
              e.target.value = "";
            }}
          />
        </div>

        {/* Step 2: pick checklist */}
        <div>
          <div className="text-[0.72rem] font-bold uppercase tracking-wide text-muted mb-1.5">2. Checklist</div>
          <div className="flex flex-col gap-2">
            <label
              className={`flex items-center gap-2.5 border rounded-lg px-3 py-2.5 cursor-pointer ${
                checklistSource === "default" ? "border-accent bg-accent-tint" : "border-border"
              }`}
            >
              <input type="radio" name="checklist-source" checked={checklistSource === "default"} onChange={() => setChecklistSource("default")} className="accent-accent" />
              <div className="min-w-0">
                <div className="text-sm font-semibold">{DEFAULT_CHECKLIST_LABEL}</div>
                <div className="text-[0.74rem] text-muted">{defaultChecklistMeta ? `${defaultChecklistMeta.n} items` : "The system's default checklist"}</div>
              </div>
            </label>

            <label
              className={`flex items-center gap-2.5 border rounded-lg px-3 py-2.5 cursor-pointer ${
                checklistSource === "custom" ? "border-accent bg-accent-tint" : "border-border"
              }`}
            >
              <input type="radio" name="checklist-source" checked={checklistSource === "custom"} onChange={() => setChecklistSource("custom")} className="accent-accent" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">Upload a different checklist (JSON)</div>
                <div className="text-[0.74rem] text-muted truncate">
                  {customChecklist ? `${customChecklist.name} · ${customChecklist.items.length} items` : "No file chosen"}
                </div>
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  setChecklistSource("custom");
                  checklistInputRef.current?.click();
                }}
                className="shrink-0 text-[0.76rem] font-semibold border border-border rounded-lg px-2.5 py-1 hover:bg-black/3"
              >
                Choose file
              </button>
            </label>
            <input
              ref={checklistInputRef}
              type="file"
              accept="application/json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) pickChecklistFile(f);
                e.target.value = "";
              }}
            />
            {customChecklistError && <div className="text-[0.78rem] text-fail px-1">{customChecklistError}</div>}
          </div>
        </div>

        {submitError && <div className="text-sm text-fail bg-fail-bg rounded-lg px-3 py-2">{submitError}</div>}

        <div className="flex items-center gap-2">
          {canCancel && (
            <button type="button" onClick={onCancel} className="text-sm font-semibold border border-border rounded-lg px-4 py-2 hover:bg-black/3">
              Cancel
            </button>
          )}
          <button
            type="button"
            onClick={handleStart}
            disabled={!canStart}
            className="flex-1 text-sm font-semibold bg-accent text-white rounded-lg py-2.5 hover:bg-accent-dark disabled:opacity-40 disabled:cursor-default flex items-center justify-center gap-2"
          >
            {submitting || loadingDefault ? (
              <>
                <span className="spinner" /> Processing...
              </>
            ) : (
              "Upload & start analysis"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
