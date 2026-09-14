"use client";

import { motion } from "framer-motion";
import {
  LayoutDashboard,
  FileText,
  Hammer,
  CheckCircle2,
  Settings,
  Search,
  Circle,
} from "lucide-react";

/**
 * Full-width hero product mockup — a stylized dashboard screenshot echoing
 * the Tsenta hero: left rail nav, top "job matches" cards with match rings,
 * and an applications table. Purely presentational.
 */

const NAV = [
  { icon: LayoutDashboard, label: "Dashboard", active: true },
  { icon: Search, label: "Matches" },
  { icon: FileText, label: "Leads" },
  { icon: CheckCircle2, label: "Review" },
  { icon: Hammer, label: "Builds" },
];

const MATCHES = [
  { company: "Northwind", role: "Backend Engineer", score: "Strong", tint: "bg-amber-50" },
  { company: "Atlas", role: "Full-Stack Engineer", score: "Strong", tint: "bg-emerald-50" },
  { company: "Meridian", role: "Software Engineer", score: "Good", tint: "bg-violet-50" },
  { company: "Kestrel", role: "Platform Engineer", score: "Good", tint: "bg-rose-50" },
];

const ROWS = [
  { company: "Migma AI", role: "Backend Engineer", channel: "Outreach", status: "Sent", ok: true, when: "2 days ago" },
  { company: "Gridlane", role: "Software Engineer, Backend", channel: "Outreach", status: "Draft ready", ok: null, when: "1 day ago" },
  { company: "Strix Group", role: "Full-Stack Engineer", channel: "Outreach", status: "Tailoring resume", ok: null, when: "1 day ago" },
  { company: "Everts", role: "Platform Engineer", channel: "Outreach", status: "In review", ok: null, when: "1 day ago" },
  { company: "Kestrel", role: "Software Engineer", channel: "Outreach", status: "New lead", ok: false, when: "3 hours ago" },
];

export function HeroDashboard() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 32 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.8, delay: 0.25, ease: [0.21, 1.02, 0.73, 1] }}
      className="relative mx-auto w-full max-w-5xl overflow-hidden rounded-2xl border border-border/80 bg-card shadow-[0px_24px_80px_-24px_rgba(0,0,0,0.28)]"
    >
      <div className="flex min-h-[420px]">
        {/* Left rail */}
        <aside className="hidden w-52 shrink-0 flex-col border-r border-border/70 bg-muted/30 p-3 sm:flex">
          <div className="flex items-center gap-2 px-2 py-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary text-[11px] font-bold text-primary-foreground">
              O
            </div>
            <span className="font-display text-sm text-foreground">Outra</span>
          </div>
          <div className="mt-4 space-y-0.5">
            {NAV.map((item) => (
              <div
                key={item.label}
                className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs font-medium ${item.active
                  ? "bg-card text-foreground shadow-[0px_1px_2px_0px_rgba(0,0,0,0.05)]"
                  : "text-muted-foreground"
                  }`}
              >
                <item.icon className="h-3.5 w-3.5" />
                {item.label}
              </div>
            ))}
          </div>
          <div className="mt-auto flex items-center gap-2 rounded-lg bg-primary px-2.5 py-2">
            <div className="h-6 w-6 rounded-full bg-brand/80" />
            <div className="leading-tight">
              <p className="text-[11px] font-medium text-primary-foreground">Alex Morgan</p>
              <p className="text-[9px] text-primary-foreground/60">Pro plan</p>
            </div>
          </div>
        </aside>

        {/* Main */}
        <div className="min-w-0 flex-1 p-4 sm:p-5">
          {/* Topbar */}
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-semibold text-foreground">Dashboard</span>
            <div className="hidden items-center gap-2 rounded-lg border border-border/70 bg-muted/40 px-3 py-1.5 sm:flex">
              <Search className="h-3 w-3 text-muted-foreground" />
              <span className="text-[11px] text-muted-foreground">Search roles, companies…</span>
            </div>
          </div>

          {/* Match cards */}
          <p className="mt-4 text-[11px] font-medium text-muted-foreground">Top job matches</p>
          <div className="mt-2 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
            {MATCHES.map((m, i) => (
              <motion.div
                key={m.company}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 + i * 0.08 }}
                className={`rounded-xl border border-border/60 ${m.tint} p-3`}
              >
                <p className="text-[9px] font-medium uppercase tracking-wide text-muted-foreground">
                  {m.company}
                </p>
                <div className="mt-1 flex items-end justify-between gap-2">
                  <p className="text-[11px] font-semibold leading-tight text-foreground">
                    {m.role}
                  </p>
                  <span className="shrink-0 rounded-full bg-white/70 px-1.5 py-0.5 text-[8px] font-semibold uppercase tracking-wide text-foreground/70">
                    {m.score}
                  </span>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Applications table */}
          <div className="mt-4 flex items-center justify-between">
            <p className="text-[11px] font-medium text-muted-foreground">All applications</p>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[9px] font-medium text-muted-foreground">
              Auto-tracked
            </span>
          </div>
          <div className="mt-2 overflow-hidden rounded-xl border border-border/60">
            {ROWS.map((r, i) => (
              <motion.div
                key={r.company}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.7 + i * 0.07 }}
                className={`flex items-center gap-3 px-3 py-2.5 text-[11px] ${i !== ROWS.length - 1 ? "border-b border-border/50" : ""
                  }`}
              >
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-[9px] font-semibold text-muted-foreground">
                  {r.company.charAt(0)}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-foreground">{r.company}</p>
                  <p className="truncate text-[10px] text-muted-foreground">{r.role}</p>
                </div>
                <span className="hidden w-14 shrink-0 text-muted-foreground sm:block">{r.channel}</span>
                <span className="flex w-28 shrink-0 items-center gap-1.5">
                  <Circle
                    className={`h-1.5 w-1.5 fill-current ${r.ok === true ? "text-emerald-500" : r.ok === false ? "text-muted-foreground" : "text-brand"
                      }`}
                  />
                  <span className="truncate text-foreground/80">{r.status}</span>
                </span>
                <span className="hidden w-16 shrink-0 text-right text-muted-foreground md:block">
                  {r.when}
                </span>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
