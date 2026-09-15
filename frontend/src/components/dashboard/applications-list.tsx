"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/ui/panel";
import { staggerContainer, fadeInUp } from "@/lib/motion";
import type { Lead } from "@/lib/api";

/**
 * Compact "All applications" list for the dashboard, matching the reference:
 * an avatar initial, the company with its role beneath, the outreach channel,
 * a colored status dot + label, and a relative timestamp. Rows link through
 * to the lead detail. This is intentionally lighter than the full filterable
 * ApplicationsTable used on the /leads page.
 */

const STATUS_STYLE: Record<string, { label: string; dot: string; text: string }> = {
  sent: { label: "Sent", dot: "bg-emerald-500", text: "text-emerald-700" },
  replied: { label: "Replied", dot: "bg-violet-500", text: "text-violet-700" },
  new: { label: "New lead", dot: "bg-slate-400", text: "text-muted-foreground" },
  matched: { label: "New lead", dot: "bg-slate-400", text: "text-muted-foreground" },
  pending_review: { label: "In review", dot: "bg-amber-500", text: "text-amber-700" },
  in_review: { label: "In review", dot: "bg-amber-500", text: "text-amber-700" },
  approved: { label: "Approved", dot: "bg-blue-500", text: "text-blue-700" },
  draft_created: { label: "Draft ready", dot: "bg-orange-500", text: "text-orange-700" },
  approved_needs_gmail: { label: "Needs Gmail", dot: "bg-amber-500", text: "text-amber-700" },
  send_failed: { label: "Send failed", dot: "bg-red-500", text: "text-red-700" },
  rejected: { label: "Rejected", dot: "bg-slate-400", text: "text-muted-foreground" },
  send_skipped: { label: "Not sent", dot: "bg-slate-400", text: "text-muted-foreground" },
};

function relativeTime(lead: Lead): string {
  const raw = lead.sent_at || lead.applied_at || lead.posted_date || lead.last_checked || "";
  if (!raw) return "—";
  const d = new Date(raw);
  if (isNaN(d.getTime())) return raw;
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hour${hrs === 1 ? "" : "s"} ago`;
  const days = Math.floor(hrs / 24);
  if (days === 1) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  return `${months} month${months === 1 ? "" : "s"} ago`;
}

function channelLabel(lead: Lead): string {
  if (Array.isArray(lead.channel) && lead.channel.includes("apply")) return "Apply";
  return "Outreach";
}

export function ApplicationsList({ leads }: { leads: Lead[] }) {
  const rows = [...leads]
    .sort((a, b) =>
      (b.sent_at || b.applied_at || b.posted_date || "").localeCompare(
        a.sent_at || a.applied_at || a.posted_date || ""
      )
    )
    .slice(0, 8);

  return (
    <Panel className="overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3.5">
        <h3 className="text-sm font-medium text-muted-foreground">All applications</h3>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2.5 py-1 text-[10px] font-medium text-muted-foreground">
          Auto-tracked
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="border-t border-border/60 px-5 py-12 text-center text-sm text-muted-foreground">
          Nothing here yet — save a match to start your pipeline.
        </div>
      ) : (
        <motion.div
          variants={staggerContainer(0.05)}
          initial="hidden"
          animate="show"
          className="border-t border-border/60"
        >
          {rows.map((lead) => {
            const s = STATUS_STYLE[lead.status] || STATUS_STYLE.new;
            const company = lead.company || (lead.x_handle ? `@${lead.x_handle}` : "—");
            return (
              <motion.div key={lead.id} variants={fadeInUp}>
                <Link
                  href={`/leads?lead=${lead.id}`}
                  className="grid grid-cols-[auto_1fr_auto] items-center gap-4 border-b border-border/50 px-5 py-3 transition-colors last:border-0 hover:bg-muted/30 sm:grid-cols-[auto_1fr_5rem_7rem_5.5rem]"
                >
                  {/* Avatar */}
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold text-muted-foreground">
                    {company.charAt(0).toUpperCase()}
                  </div>

                  {/* Company + role (centered like the reference) */}
                  <div className="min-w-0 text-center sm:text-left">
                    <p className="truncate text-sm font-semibold text-foreground">{company}</p>
                    <p className="truncate text-xs text-muted-foreground">{lead.role || "—"}</p>
                  </div>

                  {/* Channel */}
                  <span className="hidden text-xs text-muted-foreground sm:block">
                    {channelLabel(lead)}
                  </span>

                  {/* Status */}
                  <span className={cn("hidden items-center gap-1.5 text-xs font-medium sm:flex", s.text)}>
                    <span className={cn("h-1.5 w-1.5 rounded-full", s.dot)} />
                    {s.label}
                  </span>

                  {/* Time */}
                  <span className="whitespace-nowrap text-right text-xs tabular-nums text-muted-foreground">
                    {relativeTime(lead)}
                  </span>
                </Link>
              </motion.div>
            );
          })}
        </motion.div>
      )}
    </Panel>
  );
}
