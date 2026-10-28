import { useState } from "react";
import { api } from "../services/api";
import { useAsync, toApiError } from "../hooks/useAsync";
import { Modal } from "./Modal";
import { Async, Banner, Button } from "./ui";
import { useToast } from "./Toast";

interface Props {
  kind: "scan" | "cleaning";
  targetId: string;
  emailConfigured: boolean;
  open: boolean;
  onClose: () => void;
}

/** Shows exactly what an email report contains (counts only) and lets you send it. */
export function ReportDialog({ kind, targetId, emailConfigured, open, onClose }: Props) {
  return (
    <Modal open={open} onClose={onClose} title="Email report preview" wide>
      <ReportBody kind={kind} targetId={targetId} emailConfigured={emailConfigured} onClose={onClose} />
    </Modal>
  );
}

function ReportBody({ kind, targetId, emailConfigured, onClose }: Omit<Props, "open">) {
  const toast = useToast();
  const [sending, setSending] = useState(false);
  const preview = useAsync(
    () => (kind === "scan" ? api.previewScanReport(targetId) : api.previewCleanedReport(targetId)),
    [kind, targetId]);

  const send = async () => {
    setSending(true);
    try {
      const info = kind === "scan" ? await api.sendScanReport(targetId) : await api.sendCleanedReport(targetId);
      if (info.status === "sent") { toast.success("Report sent", `Delivered to ${info.recipient_masked}.`); onClose(); }
      else toast.error("Report could not be sent", info.error_message ?? "Check the email settings.");
    } catch (e) {
      toast.error("Report could not be sent", toApiError(e).message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-3">
      <Async state={preview} label="Preparing preview…">
        {(p) => (
          <>
            <p className="text-sm"><span className="font-semibold">Subject:</span> {p.subject}</p>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs leading-relaxed dark:bg-slate-800">{p.text}</pre>
            <p className="text-xs text-slate-500">The report body contains summary information. Cleaning report emails also include the generated cleaned CSV as an attachment.</p>
            {emailConfigured
              ? <div className="flex justify-end"><Button onClick={send} loading={sending}>Send this report now</Button></div>
              : <Banner kind="info" title="Email is not configured">Set the SMTP values in the backend <code>.env</code> to send reports (see Settings).</Banner>}
          </>
        )}
      </Async>
    </div>
  );
}
