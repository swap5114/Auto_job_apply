"use client";

import { useState } from "react";
import { Send, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

/**
 * Sends (or drafts, depending on GMAIL_DIRECT_SEND) all approved leads via
 * Gmail. Reports a clear summary — including how many were skipped because
 * they have no email (e.g. X leads), which is the usual reason "0 sent".
 */
export function SendApprovedButton({
  count,
  onDone,
  variant = "outline",
  size = "sm",
}: {
  count?: number;
  onDone?: () => void;
  variant?: "default" | "outline" | "ghost" | "secondary";
  size?: "default" | "sm" | "lg" | "icon";
}) {
  const [busy, setBusy] = useState(false);

  async function handleSend() {
    setBusy(true);
    try {
      const res = await api.pipeline.send();
      const s = res.summary;

      if (s.error) {
        toast.error(`Gmail error: ${s.error}`);
        return;
      }

      if (s.total === 0) {
        toast.info("No approved leads to send.");
      } else {
        const parts: string[] = [];
        if (res.mode === "direct" && s.sent) parts.push(`${s.sent} sent`);
        if (res.mode === "drafts" && s.draft_created) parts.push(`${s.draft_created} drafts created`);
        if (s.skipped_no_email) parts.push(`${s.skipped_no_email} skipped (no email)`);
        if (s.skipped_quota) parts.push(`${s.skipped_quota} skipped (monthly limit reached)`);
        if (s.failed) parts.push(`${s.failed} failed`);
        const msg = parts.length ? parts.join(", ") : "Nothing to send";
        if ((res.mode === "direct" && s.sent) || (res.mode === "drafts" && s.draft_created)) {
          toast.success(msg + (res.mode === "drafts" ? " — review them in Gmail" : ""));
        } else {
          toast.warning(msg);
        }
      }
      onDone?.();
    } catch (e: any) {
      toast.error(e?.message || "Send failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button variant={variant} size={size} onClick={handleSend} disabled={busy}>
      {busy ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <Send className="mr-2 h-3.5 w-3.5" />}
      {busy ? "Sending…" : `Send Approved${count ? ` (${count})` : ""}`}
    </Button>
  );
}
