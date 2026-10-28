import { useRef, useState, type DragEvent } from "react";
import { formatBytes } from "../utils/format";

interface Props {
  file: File | null;
  onFile: (file: File | null) => void;
  disabled?: boolean;
  maxMb: number;
}

export function FileDropzone({ file, onFile, disabled, maxMb }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (disabled) return;
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onFile(dropped);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={`rounded-xl border-2 border-dashed p-8 text-center transition ${over ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/40" : "border-slate-300 dark:border-slate-700"} ${disabled ? "opacity-60" : ""}`}
    >
      <input ref={input} id="csv-file" type="file" accept=".csv,text/csv" className="sr-only" disabled={disabled}
             aria-label="Choose a CSV file"
             onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
      {file ? (
        <div>
          <p className="break-all font-semibold">{file.name}</p>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{formatBytes(file.size)}</p>
          <button type="button" disabled={disabled} onClick={() => { onFile(null); if (input.current) input.current.value = ""; }}
                  className="mt-3 text-sm text-indigo-600 hover:underline disabled:opacity-50 dark:text-indigo-400">
            Choose a different file
          </button>
        </div>
      ) : (
        <div>
          <p className="font-semibold">Drag a CSV file here</p>
          <p className="my-1 text-sm text-slate-500">or</p>
          <label htmlFor="csv-file"
                 className={`inline-block cursor-pointer rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 ${disabled ? "pointer-events-none" : ""}`}>
            Browse files
          </label>
          <p className="mt-3 text-xs text-slate-500">.csv only · up to {maxMb} MB</p>
        </div>
      )}
    </div>
  );
}
