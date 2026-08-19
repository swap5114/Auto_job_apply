"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  ArrowUpRight,
  Briefcase,
  Globe,
  Twitter,
  Building2,
  Rocket,
  Send,
  MailOpen,
  FileText,
  Clock,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import { DonutChart } from "@/components/ui/donut-chart";
import { RunPipelineButton } from "@/components/pipeline/run-pipeline-dialog";
import { staggerContainer, fadeInUp, scaleIn, slideInLeft } from "@/lib/motion";
import { api, type Lead, type Stats } from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SOURCE_ICONS: Record<string, typeof Briefcase> = {
  arbeitnow: Briefcase,
  jobicy: Globe,
  yc: Rocket,
  company_list: Building2,
  careers_page: Building2,
  x: Twitter,
};

function Panel({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={`rounded-2xl border border-border/70 bg-card shadow-card ${className}`}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [s, l] = await Promise.all([api.stats.get(), api.leads.list()]);
      setStats(s);
      setLeads(l);
    } catch (e: any) {
      setError(e?.message || "Failed to load dashboard data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  // Derived metrics from real leads
  const sourceCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const l of leads) {
      const src = l.source || "unknown";
      counts[src] = (counts[src] || 0) + 1;
    }
    return Object.entries(counts)
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);
  }, [leads]);

  const maxSource = Math.max(1, ...sourceCounts.map((s) => s.count));

  const funnel = useMemo(() => {
    const total = leads.length;
    const has = (pred: (l: Lead) => boolean) => leads.filter(pred).length;
    const tailored = has((l) => !!l.resume_version);
    const drafted = has((l) => !!l.outreach_draft);
    const sent = has((l) => l.status === "sent" || l.status === "draft_created" || l.status === "replied");
    const replied = has((l) => l.status === "replied");
    const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);
    return [
      { stage: "Sourced", count: total, pct: 100 },
      { stage: "Tailored", count: tailored, pct: pct(tailored) },
      { stage: "Drafted", count: drafted, pct: pct(drafted) },
      { stage: "Sent", count: sent, pct: pct(sent) },
      { stage: "Replied", count: replied, pct: pct(replied) },
    ];
  }, [leads]);

  const sentCount = stats?.sent ?? 0;
  const repliedCount = stats?.replied ?? 0;
  const replyRate = sentCount > 0 ? Math.round((repliedCount / sentCount) * 100) : 0;

  const kpis = [
    { label: "Total Leads", value: stats?.total ?? 0, icon: FileText },
    { label: "Pending Review", value: (stats?.pending_review ?? 0) + (stats?.in_review ?? 0), icon: Clock },
    { label: "Sent", value: sentCount, icon: Send },
    { label: "Reply Rate", value: replyRate, icon: MailOpen, suffix: "%" },
  ];

  const recentActivity = useMemo(() => {
    // Most recent leads by posted_date (fallback: array order)
    return [...leads]
      .sort((a, b) => (b.posted_date || "").localeCompare(a.posted_date || ""))
      .slice(0, 6)
      .map((l) => ({
        text: l.company
          ? `${statusVerb(l.status)} — ${l.company}`
          : l.x_handle
            ? `${statusVerb(l.status)} — @${l.x_handle}`
            : statusVerb(l.status),
        meta: l.role || l.source,
        date: l.posted_date || "",
      }));
  }, [leads]);

  return (
    <PageTransition>
      <Header
        title="Dashboard"
        description="Your outreach pipeline at a glance"
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={load} disabled={loading}>
              <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <RunPipelineButton />
          </div>
        }
      />

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error} — is the API running on port 8000?
        </div>
      )}

      {loading && !stats ? (
        <div className="flex items-center justify-center py-32 text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Loading dashboard…
        </div>
      ) : (
        <div className="space-y-4 pb-16">
          {/* KPI ROW */}
          <motion.div
            className="grid grid-cols-2 gap-4 lg:grid-cols-4"
            variants={staggerContainer(0.07)}
            initial="hidden"
            animate="show"
          >
            {kpis.map((kpi) => (
              <motion.div key={kpi.label} variants={scaleIn}>
                <div className="group relative overflow-hidden rounded-2xl border border-border/70 bg-card p-5 shadow-card transition-shadow duration-300 hover:shadow-card-hover">
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <kpi.icon className="h-3.5 w-3.5" />
                    <span className="text-xs font-medium">{kpi.label}</span>
                  </div>
                  <div className="mt-4">
                    <AnimatedCounter
                      value={kpi.value}
                      suffix={kpi.suffix ?? ""}
                      className="font-display text-[2rem] leading-none tabular-nums text-foreground"
                    />
                  </div>
                </div>
              </motion.div>
            ))}
          </motion.div>

          {/* FUNNEL + DONUT */}
          <div className="grid gap-4 lg:grid-cols-3">
            <motion.div className="lg:col-span-2" variants={fadeInUp} initial="hidden" animate="show">
              <Panel className="h-full p-6">
                <div className="mb-5 flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">Pipeline Funnel</h3>
                    <p className="text-xs text-muted-foreground">Conversion across every stage</p>
                  </div>
                  <span className="rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium tabular-nums text-muted-foreground">
                    {leads.length} total
                  </span>
                </div>
                <div className="space-y-2.5">
                  {funnel.map((item, i) => (
                    <div key={item.stage} className="flex items-center gap-3">
                      <div className="w-16 shrink-0 text-right text-xs font-medium text-muted-foreground">
                        {item.stage}
                      </div>
                      <div className="relative h-8 flex-1 overflow-hidden rounded-lg bg-muted/50">
                        <motion.div
                          className="absolute inset-y-0 left-0 rounded-lg accent-gradient"
                          style={{ opacity: 0.35 + (item.pct / 100) * 0.65 }}
                          initial={{ width: 0 }}
                          animate={{ width: `${item.pct}%` }}
                          transition={{ duration: 0.9, delay: 0.15 + i * 0.08, ease: [0.21, 1.02, 0.73, 1] }}
                        />
                        <div className="absolute inset-0 flex items-center justify-between px-3">
                          <span className="text-xs font-semibold tabular-nums text-foreground">
                            {item.count}
                          </span>
                          <span className="text-[11px] font-medium tabular-nums text-muted-foreground">
                            {item.pct}%
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>
            </motion.div>

            <motion.div variants={scaleIn} initial="hidden" animate="show">
              <Panel className="flex h-full flex-col p-6">
                <h3 className="text-sm font-semibold text-foreground">Reply Rate</h3>
                <p className="text-xs text-muted-foreground">Replies vs. sent</p>
                <div className="flex flex-1 items-center justify-center py-4">
                  <DonutChart
                    segments={[
                      { label: "Replied", value: repliedCount, color: "accent" },
                      { label: "No reply", value: Math.max(0, sentCount - repliedCount), color: "hsl(var(--muted))" },
                    ]}
                    center={
                      <>
                        <span className="font-display text-3xl tabular-nums text-foreground">
                          <AnimatedCounter value={replyRate} suffix="%" />
                        </span>
                        <span className="text-[11px] text-muted-foreground">
                          {repliedCount} of {sentCount}
                        </span>
                      </>
                    }
                  />
                </div>
              </Panel>
            </motion.div>
          </div>

          {/* SOURCES + ACTIVITY */}
          <div className="grid gap-4 lg:grid-cols-3">
            <motion.div variants={fadeInUp} initial="hidden" animate="show">
              <Panel className="h-full p-6">
                <h3 className="mb-5 text-sm font-semibold text-foreground">Leads by Source</h3>
                {sourceCounts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No leads yet. Run the pipeline to source some.</p>
                ) : (
                  <div className="space-y-4">
                    {sourceCounts.map((s, i) => {
                      const Icon = SOURCE_ICONS[s.name] || FileText;
                      return (
                        <div key={s.name} className="flex items-center gap-3">
                          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                          <span className="w-24 shrink-0 truncate text-sm text-foreground">{s.name}</span>
                          <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                            <motion.div
                              className="absolute inset-y-0 left-0 rounded-full accent-gradient"
                              initial={{ width: 0 }}
                              animate={{ width: `${(s.count / maxSource) * 100}%` }}
                              transition={{ duration: 0.8, delay: 0.2 + i * 0.1, ease: [0.21, 1.02, 0.73, 1] }}
                            />
                          </div>
                          <span className="w-6 shrink-0 text-right text-sm font-semibold tabular-nums text-foreground">
                            {s.count}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </Panel>
            </motion.div>

            <motion.div className="lg:col-span-2" variants={fadeInUp} initial="hidden" animate="show">
              <Panel className="h-full p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-foreground">Recent Leads</h3>
                </div>
                {recentActivity.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Nothing here yet.</p>
                ) : (
                  <motion.div
                    className="relative space-y-1"
                    variants={staggerContainer(0.06, 0.2)}
                    initial="hidden"
                    animate="show"
                  >
                    <div className="absolute bottom-3 left-[7px] top-3 w-px bg-border" />
                    {recentActivity.map((a, i) => (
                      <motion.div
                        key={i}
                        variants={slideInLeft}
                        className="relative flex items-center gap-4 rounded-lg py-2 pl-6 pr-2 transition-colors hover:bg-muted/40"
                      >
                        <span className="absolute left-1 h-2.5 w-2.5 rounded-full bg-accent1 ring-4 ring-card" />
                        <div className="flex-1">
                          <p className="text-sm text-foreground">{a.text}</p>
                          <p className="text-xs text-muted-foreground">{a.meta}</p>
                        </div>
                        <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
                          {a.date}
                        </span>
                      </motion.div>
                    ))}
                  </motion.div>
                )}
              </Panel>
            </motion.div>
          </div>
        </div>
      )}
    </PageTransition>
  );
}

function statusVerb(status: string): string {
  const map: Record<string, string> = {
    new: "New lead",
    pending_review: "Awaiting review",
    in_review: "In review",
    approved: "Approved",
    sent: "Email sent",
    draft_created: "Draft created",
    replied: "Replied",
    rejected: "Rejected",
  };
  return map[status] || "Lead";
}
