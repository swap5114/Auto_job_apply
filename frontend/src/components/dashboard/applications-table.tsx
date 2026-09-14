"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Search, FileText, ArrowRight } from "lucide-react";
import { Panel } from "@/components/ui/panel";
import { cn } from "@/lib/utils";
import type { Lead } from "@/lib/api";

/**
 * "Your applications" table — a dense, scannable list of every lead the user
 * is pursuing, with resume readiness, current status, and when it was
 * applied. Filter chips + search up top, rows link to the lead detail.
 */

type Bucket = "all" | "submitted" | "in_flight" | "needs_you" | "failed" | "skipped";

const BUCKET_LABEL: Record<Bucket, string> = {
  all: "All",
  submitted: "Submitted",
  in_flight: "In flight",
  needs_you: "Needs you",
  failed: "Failed",
  skipped: "Skipped",
};

function bucketOf(status: string): Bucket {
  switch (status) {
    case "sent":
    case "replied":
      return "submitted";
    case "new":
    case "pending_review":
    case "in_review":
    case "approved":
    case "draft_created":
      return "in_flight";
    case "approved_needs_gmail":
      return "needs_you";
    case "send_failed":
      return "failed";
    case "rejected":
    case "send_skipped":
      return "skipped";
    default:
      return "in_flight";
  }
}

const STATUS_STYLE: Record<string, { label: string; dot: string; text: string }> = {
  sent: { label: "Submitted", dot: "bg-emerald-500", text: "text-emerald-700" },
  replied: { label: "Replied", dot: "bg-violet-500", text: "text-violet-700" },
  new: { label: "New", dot: "bg-slate-400", text: "text-muted-foreground" },
  pending_review: { label: "In review", dot: "bg-amber-500", text: "text-amber-700" },
  in_review: { label: "In review", dot: "bg-amber-500", text: "text-amber-700" },
  approved: { label: "Approved", dot: "bg-blue-500", text: "text-blue-700" },
  draft_created: { label: "Draft ready", dot: "bg-accent1", text: "text-accent1" },
  approved_needs_gmail: { label: "Needs Gmail", dot: "bg-amber-500", text: "text-amber-700" },
  send_failed: { label: "Failed", dot: "bg-red-500", text: "text-red-700" },
  rejected: { label: "Rejected", dot: "bg-red-400", text: "text-muted-foreground" },
  send_skipped: { label: "Skipped", dot: "bg-slate-400", text: "text-muted-foreground" },
};

/**
 * Precise resume state from real backend data:
 *  - keyword_coverage (0-100 ATS match on the tailored resume) when present,
 *  - else "Ready" if a tailored resume_version exists,
 *  - else "Pending" (not tailored yet).
 */
function resumeState(lead: Lead): { label: string; tone: "good" | "ok" | "none" } {
  const cov = lead.keyword_coverage;
  if (typeof cov === "number") {
    const pct = Math.round(cov <= 1 ? cov * 100 : cov);
    return { label: `${pct}% match`, tone: pct >= 60 ? "good" : "ok" };
  }
  if (lead.resume_version) return { label: "Ready", tone: "good" };
  return { label: "Pending", tone: "none" };
}

function appliedLabel(lead: Lead): string {
  const raw = lead.sent_at || lead.applied_at || lead.posted_date || "";
  if (!raw) return "—";
  const d = new Date(raw);
  if (isNaN(d.getTime())) return raw;
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  if (days < 60) return "a month ago";
  return `${Math.floor(days / 30)} months ago`;
}

export function ApplicationsTable({ leads }: { leads: Lead[] }) {
  const [bucket, setBucket] = useState<Bucket>("all");
  const [query, setQuery] = useState("");

  const counts = useMemo(() => {
    const c: Record<Bucket, number> = {
      all: leads.length,
      submitted: 0,
      in_flight: 0,
      needs_you: 0,
      failed: 0,
      skipped: 0,
    };
    for (const l of leads) c[bucketOf(l.status)]++;
    return c;
  }, [leads]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return leads.filter((l) => {
      if (bucket !== "all" && bucketOf(l.status) !== bucket) return false;
      if (q) {
        const hay = `${l.company} ${l.role} ${l.x_handle}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [leads, bucket, query]);

  const buckets: Bucket[] = ["all", "submitted", "in_flight", "needs_you", "failed", "skipped"];

  return (
    <Panel className="overflow-hidden">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 border-b border-border/60 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          {buckets.map((b) => {
            const active = bucket === b;
            return (
              <button
                key={b}
                onClick={() => setBucket(b)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {BUCKET_LABEL[b]}
                <span className={cn("tabular-nums", active ? "text-primary-foreground/60" : "text-muted-foreground/60")}>
                  {counts[b]}
                </span>
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-border/70 bg-muted/40 px-2.5 py-1.5 sm:w-56">
          <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search companies…"
            className="w-full bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
        </div>
      </div>

      {/* Column head */}
      <div className="hidden grid-cols-[2.5fr_1fr_1.2fr_1fr] gap-4 border-b border-border/60 bg-muted/30 px-5 py-2.5 sm:grid">
        {["Company", "Resume", "Status", "Applied"].map((h) => (
          <span key={h} className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {h}
          </span>
        ))}
      </div>

      {/* Rows */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <FileText className="h-8 w-8 text-muted-foreground/40" />
          <p className="mt-3 text-sm text-muted-foreground">No applications in this view</p>
        </div>
      ) : (
        <div className="max-h-[520px] overflow-y-auto">
          <AnimatePresence initial={false}>
            {filtered.map((lead) => {
              const resume = resumeState(lead);
              const s = STATUS_STYLE[lead.status] || STATUS_STYLE.new;
              return (
                <motion.div
                  key={lead.id}
                  layout
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  <Link
                    href={`/leads?lead=${lead.id}`}
                    className="group grid grid-cols-[2.5fr_1fr] gap-4 border-b border-border/50 px-5 py-3 transition-colors last:border-0 hover:bg-muted/30 sm:grid-cols-[2.5fr_1fr_1.2fr_1fr]"
                  >
                    {/* Company */}
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-[11px] font-semibold text-muted-foreground">
                        {(lead.company || lead.x_handle || "—").charAt(0).toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">
                          {lead.company || `@${lead.x_handle}` || "—"}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">{lead.role || "—"}</p>
                      </div>
                    </div>

                    {/* Resume */}
                    <div className="flex items-center">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 text-xs font-medium",
                          resume.tone === "good"
                            ? "text-emerald-700"
                            : resume.tone === "ok"
                              ? "text-amber-700"
                              : "text-muted-foreground"
                        )}
                      >
                        <span
                          className={cn(
                            "h-1.5 w-1.5 rounded-full",
                            resume.tone === "good"
                              ? "bg-emerald-500"
                              : resume.tone === "ok"
                                ? "bg-amber-500"
                                : "bg-slate-300"
                          )}
                        />
                        {resume.label}
                      </span>
                    </div>

                    {/* Status */}
                    <div className="hidden items-center sm:flex">
                      <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", s.text)}>
                        <span className={cn("h-1.5 w-1.5 rounded-full", s.dot)} />
                        {s.label}
                      </span>
                    </div>

                    {/* Applied */}
                    <div className="hidden items-center justify-between sm:flex">
                      <span className="text-xs tabular-nums text-muted-foreground">{appliedLabel(lead)}</span>
                      <ArrowRight className="h-3.5 w-3.5 -translate-x-1 text-muted-foreground/0 transition-all group-hover:translate-x-0 group-hover:text-muted-foreground" />
                    </div>
                  </Link>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}
    </Panel>
  );
}
