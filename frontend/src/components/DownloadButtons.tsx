import { useState } from "react";
import { api } from "../services/api";
import { toApiError } from "../hooks/useAsync";
import type { DownloadMode } from "../types/api";
import { saveBlob } from "../utils/download";
import { Button } from "./ui";
import { useToast } from "./Toast";

/** Two download choices: spreadsheet-safe (default) and raw exact values. */
export function DownloadButtons({ cleanedId, disabled }: { cleanedId: string; disabled?: boolean }) {
  const toast = useToast();
  const [busy, setBusy] = useState<DownloadMode | null>(null);

  const download = async (mode: DownloadMode) => {
    setBusy(mode);
    try {
      const { blob, filename, cellsEscaped } = await api.downloadCleaned(cleanedId, mode);
      saveBlob(blob, filename);
      toast.success("Download started",
        mode === "safe" && cellsEscaped
          ? `${cellsEscaped} cell(s) starting with = + - or @ were prefixed with ' so spreadsheets show them as text.`
          : filename);
    } catch (e) {
      toast.error("Download failed", toApiError(e).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-wrap gap-2">
      <Button onClick={() => download("safe")} loading={busy === "safe"} disabled={disabled || busy !== null}>
        Download CSV (safe for Excel)
      </Button>
      <Button variant="secondary" onClick={() => download("raw")} loading={busy === "raw"} disabled={disabled || busy !== null}>
        Download raw CSV
      </Button>
    </div>
  );
}
