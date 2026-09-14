"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Send,
  MailOpen,
  FileText,
  Loader2,
  RefreshCw,
  Sparkles,
  CheckCircle2,
  Inbox,
  Square,
  Play,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import { DonutChart } from "@/components/ui/donut-chart";
import { QuotaCard } from "@/components/dashboard/quota-card";
import { MatchesStrip } from "@/components/dashboard/matches-strip";
import { ApplicationsTable } from "@/components/dashboard/applications-table";
import { RunPipelineButton, RunPipelineDialog } from "@/components/pipeline/run-pipeline-dialog";
import { SendApprovedButton } from "@/components/pipeline/send-approved-button";
import { usePipelineStatus } from "@/lib/use-pipeline-status";
import { deriveQuota, quotaFromApi, type OutreachQuota } from "@/lib/quota";
import { staggerContainer, fadeInUp, scaleIn, slideInLeft } from "@/lib/motion";
import { api, type Lead, type Stats, type MatchedJob } from "@/lib/api";

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
    approved_needs_gmail: "Approved — needs Gmail",
    send_failed: "Send failed",
    send_skipped: "Not sent",
  };
  return map[status] || "Lead";
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [matches, setMatches] = useState<MatchedJob[]>([]);
  const [matchCount, setMatchCount] = useState<number | null>(null);
  const [hasCriteria, setHasCriteria] = useState<boolean | null>(null);
  const [quota, setQuota] = useState<OutreachQuota | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runOpen, setRunOpen] = useState(false);

  const { state, abort, aborting } = usePipelineStatus();
  const running = state?.running ?? false;

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [s, l] = await Promise.all([api.stats.get(), api.leads.list()]);
      setStats(s);
      setLeads(l);
      // Real, server-enforced outreach quota. Fall back to deriving from
      // stats only if the endpoint is unavailable.
      api.outreach
        .quota()
        .then((q) => setQuota(quotaFromApi(q)))
        .catch(() => setQuota(deriveQuota(s)));
    } catch (e: any) {
      setError(e?.message || "Failed to load dashboard data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // Match count + criteria drive the "next action" when the queue is empty.
    Promise.all([
      api.jobs.matched().catch(() => []),
      api.profile.getSearchCriteria().then(() => true).catch(() => false),
    ]).then(([m, c]) => {
      const list = Array.isArray(m) ? m : [];
      setMatches(list);
      setMatchCount(list.length);
      setHasCriteria(c);
    });
  }, []);

  // --- Real derived numbers ------------------------------------------------
  const pendingReview = (stats?.pending_review ?? 0) + (stats?.in_review ?? 0);
  const sentCount = stats?.sent ?? 0;
  const repliedCount = stats?.replied ?? 0;
  const replyRate = sentCount > 0 ? Math.round((repliedCount / sentCount) * 100) : 0;

  const sendableCount = useMemo(
    () =>
      leads.filter(
        (l) =>
          (l.status === "approved" || l.status === "draft_created") &&
          (l.contact_email || "").trim()
      ).length,
    [leads]
  );
  const needsGmailCount = useMemo(
    () => leads.filter((l) => l.status === "approved_needs_gmail").length,
    [leads]
  );

  const funnel = useMemo(() => {
    const total = leads.length;
    const has = (pred: (l: Lead) => boolean) => leads.filter(pred).length;
    const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);
    const tailored = has((l) => !!l.resume_version);
    const drafted = has((l) => !!l.outreach_draft);
    const sent = has((l) => ["sent", "draft_created", "replied"].includes(l.status));
    const replied = has((l) => l.status === "replied");
    return [
      { stage: "Sourced", count: total, pct: 100 },
      { stage: "Tailored", count: tailored, pct: pct(tailored) },
      { stage: "Drafted", count: drafted, pct: pct(drafted) },
      { stage: "Sent", count: sent, pct: pct(sent) },
      { stage: "Replied", count: replied, pct: pct(replied) },
    ];
  }, [leads]);

  const recent = useMemo(
    () =>
      [...leads]
        .sort((a, b) => (b.posted_date || "").localeCompare(a.posted_date || ""))
        .slice(0, 5)
        .map((l) => ({
          text: l.company ? `${statusVerb(l.status)} — ${l.company}` : statusVerb(l.status),
          meta: l.role || l.source,
          date: l.posted_date || "",
        })),
    [leads]
  );

  const kpis = [
    { label: "Total leads", value: stats?.total ?? 0, icon: FileText, href: "/leads" },
    { label: "Sent", value: sentCount, icon: Send, href: "/leads?status=sent" },
    { label: "Replies", value: repliedCount, icon: Inbox, href: "/leads?status=replied" },
    { label: "Reply rate", value: replyRate, suffix: "%", icon: MailOpen, href: "/leads" },
  ];

  return (
    <PageTransition>
      <Header
        title="Dashboard"
        description="Your outreach at a glance — and what to do next"
        action={
          <>
            <Button variant="outline" size="sm" onClick={load} disabled={loading}>
              <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            {running ? (
              <Button variant="outline" size="sm" onClick={abort} disabled={aborting}>
                {aborting ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Square className="mr-2 h-3 w-3 fill-current text-destructive" />
                )}
                {aborting ? "Aborting…" : "Abort run"}
              </Button>
            ) : (
              <RunPipelineButton />
            )}
          </>
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
        <div className="space-y-6 pb-16">
          {/* ROW 1 — the single most important thing + the metered resource */}
          <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
            <NextAction
              running={running}
              currentStep={state?.current_step ?? null}
              onAbort={abort}
              aborting={aborting}
              pendingReview={pendingReview}
              sendableCount={sendableCount}
              needsGmailCount={needsGmailCount}
              matchCount={matchCount}
              hasCriteria={hasCriteria}
              leadCount={leads.length}
              onRun={() => setRunOpen(true)}
              onSent={load}
            />
            {quota ? (
              <QuotaCard quota={quota} />
            ) : (
              <div className="h-full min-h-[180px] animate-pulse rounded-2xl border border-border/70 bg-card shadow-card" />
            )}
          </div>

          {/* ROW 1.5 — top 5 matches, the "wow" surface */}
          {matches.length > 0 && <MatchesStrip jobs={matches} />}

          {/* ROW 2 — dense metric strip, each tile is a drill-down link */}
          <motion.div
            className="grid grid-cols-2 gap-4 lg:grid-cols-4"
            variants={staggerContainer(0.06)}
            initial="hidden"
            animate="show"
          >
            {kpis.map((kpi) => (
              <motion.div key={kpi.label} variants={scaleIn}>
                <Link href={kpi.href}>
                  <Panel interactive className="group p-5">
                    <div className="flex items-center gap-2">
                      <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent1/10 text-accent1">
                        <kpi.icon className="h-3.5 w-3.5" />
                      </span>
                      <span className="text-xs font-medium text-muted-foreground">{kpi.label}</span>
                    </div>
                    <div className="mt-3 flex items-end justify-between">
                      <AnimatedCounter
                        value={kpi.value}
                        suffix={kpi.suffix ?? ""}
                        className="font-display text-[2rem] leading-none tabular-nums text-foreground"
                      />
                      <ArrowRight className="mb-1 h-3.5 w-3.5 -translate-x-1 text-muted-foreground/0 transition-all group-hover:translate-x-0 group-hover:text-muted-foreground" />
                    </div>
                  </Panel>
                </Link>
              </motion.div>
            ))}
          </motion.div>

          {/* ROW 3 — pipeline snapshot: funnel + reply rate */}
          <div className="grid gap-4 lg:grid-cols-3">
            <motion.div className="lg:col-span-2" variants={fadeInUp} initial="hidden" animate="show">
              <Panel className="h-full p-6">
                <div className="mb-5 flex items-center justify-between">
                  <div>
                    <p className="eyebrow">Pipeline</p>
                    <h3 className="mt-1 text-sm font-semibold text-foreground">
                      Where your {leads.length} leads stand
                    </h3>
                  </div>
                  <Link
                    href="/leads"
                    className="text-xs font-medium text-accent1 hover:underline"
                  >
                    View all →
                  </Link>
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
                          style={{ opacity: 0.4 + (item.pct / 100) * 0.6 }}
                          initial={{ width: 0 }}
                          animate={{ width: `${item.pct}%` }}
                          transition={{ duration: 0.9, delay: 0.1 + i * 0.08, ease: [0.21, 1.02, 0.73, 1] }}
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
                <p className="eyebrow">Replies</p>
                <h3 className="mt-1 text-sm font-semibold text-foreground">Reply rate</h3>
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

          {/* ROW 4 — your applications */}
          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <div className="mb-3 flex items-end justify-between">
              <div>
                <p className="eyebrow">Applications</p>
                <h3 className="mt-1 text-sm font-semibold text-foreground">Your applications</h3>
              </div>
              <Link href="/leads" className="text-xs font-medium text-accent1 hover:underline">
                Open full list →
              </Link>
            </div>
            <ApplicationsTable leads={leads} />
          </motion.div>

          {/* ROW 5 — recent activity */}
          <div className="grid gap-4">
            <motion.div variants={fadeInUp} initial="hidden" animate="show">
              <Panel className="h-full p-6">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <p className="eyebrow">Activity</p>
                    <h3 className="mt-1 text-sm font-semibold text-foreground">Recent leads</h3>
                  </div>
                  <Link href="/leads" className="text-xs font-medium text-accent1 hover:underline">
                    View all →
                  </Link>
                </div>
                {recent.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Nothing here yet.</p>
                ) : (
                  <motion.div
                    className="relative space-y-1"
                    variants={staggerContainer(0.06, 0.15)}
                    initial="hidden"
                    animate="show"
                  >
                    <div className="absolute bottom-3 left-[7px] top-3 w-px bg-border" />
                    {recent.map((a, i) => (
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

      <RunPipelineDialog open={runOpen} onOpenChange={setRunOpen} />
    </PageTransition>
  );
}

/**
 * NextAction — the command-center hero. Surfaces the single most important
 * next step so the user can act without navigating away:
 *   running          → live progress + abort
 *   pending review   → review N drafts (link) + send approved (inline)
 *   sendable only    → send approved now
 *   matches ready    → save matches
 *   no criteria      → set up profile
 *   nothing sourced  → run the pipeline
 */
function NextAction({
  running,
  currentStep,
  onAbort,
  aborting,
  pendingReview,
  sendableCount,
  needsGmailCount,
  matchCount,
  hasCriteria,
  leadCount,
  onRun,
  onSent,
}: {
  running: boolean;
  currentStep: string | null;
  onAbort: () => void;
  aborting: boolean;
  pendingReview: number;
  sendableCount: number;
  needsGmailCount: number;
  matchCount: number | null;
  hasCriteria: boolean | null;
  leadCount: number;
  onRun: () => void;
  onSent: () => void;
}) {
  // 1) A run is in progress — show it, offer abort.
  if (running) {
    return (
      <HeroShell
        eyebrow="Pipeline running"
        icon={<Loader2 className="h-5 w-5 animate-spin text-accent1" />}
        title={currentStep ? `Working: ${currentStep}` : "Sourcing and preparing your outreach…"}
        body="Outra is finding roles, tailoring your resume, and drafting outreach. You can keep working — nothing sends without your approval."
      >
        <Button variant="outline" onClick={onAbort} disabled={aborting}>
          {aborting ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <Square className="mr-2 h-3 w-3 fill-current text-destructive" />}
          {aborting ? "Aborting…" : "Abort run"}
        </Button>
      </HeroShell>
    );
  }

  // 2) Drafts waiting for review — the highest-value action.
  if (pendingReview > 0) {
    return (
      <HeroShell
        eyebrow="Needs you"
        icon={<CheckCircle2 className="h-5 w-5 text-accent1" />}
        title={`${pendingReview} draft${pendingReview === 1 ? "" : "s"} waiting for your review`}
        body="Approve, edit, or reject each one. Approved messages send from your own inbox — nothing goes out until you say so."
      >
        <Button asChild>
          <Link href="/review">
            Review now
            <ArrowRight className="ml-1.5 h-4 w-4" />
          </Link>
        </Button>
        {sendableCount > 0 && <SendApprovedButton count={sendableCount} onDone={onSent} />}
      </HeroShell>
    );
  }

  // 3) Approved and ready to send.
  if (sendableCount > 0) {
    return (
      <HeroShell
        eyebrow="Ready to send"
        icon={<Send className="h-5 w-5 text-accent1" />}
        title={`${sendableCount} approved message${sendableCount === 1 ? "" : "s"} ready to send`}
        body={
          needsGmailCount > 0
            ? "Some approved messages need your Gmail connected before they can send."
            : "Send them from your inbox now, or keep them as drafts to send yourself."
        }
      >
        <SendApprovedButton count={sendableCount} onDone={onSent} variant="default" />
        {needsGmailCount > 0 && (
          <Button asChild variant="outline">
            <Link href="/settings">Connect Gmail</Link>
          </Button>
        )}
      </HeroShell>
    );
  }

  // 4) No profile yet.
  if (hasCriteria === false) {
    return (
      <HeroShell
        eyebrow="Get set up"
        icon={<Sparkles className="h-5 w-5 text-accent1" />}
        title="Set up your profile to see matches"
        body="Add your target roles and tech stack (or upload a resume) and we'll match you against every role in the catalog."
      >
        <Button asChild>
          <Link href="/profile">
            Set up profile
            <ArrowRight className="ml-1.5 h-4 w-4" />
          </Link>
        </Button>
      </HeroShell>
    );
  }

  // 5) Matches ready to save.
  if (matchCount && matchCount > 0) {
    return (
      <HeroShell
        eyebrow="Matches ready"
        icon={<Sparkles className="h-5 w-5 text-accent1" />}
        title={`${matchCount} role${matchCount === 1 ? "" : "s"} match your profile`}
        body="Save the ones worth pursuing and Outra will tailor a resume and draft outreach for each."
      >
        <Button asChild>
          <Link href="/matches">
            View matches
            <ArrowRight className="ml-1.5 h-4 w-4" />
          </Link>
        </Button>
      </HeroShell>
    );
  }

  // 6) Nothing sourced yet — run the pipeline.
  return (
    <HeroShell
      eyebrow="Start here"
      icon={<Play className="h-5 w-5 text-accent1" />}
      title={leadCount === 0 ? "Run the pipeline to source your first roles" : "You're all caught up"}
      body={
        leadCount === 0
          ? "Outra scans YC companies hiring now, tailors your resume, and drafts outreach for each — then queues it all for your review."
          : "No drafts pending and nothing to send. Run the pipeline to source new roles."
      }
    >
      <Button onClick={onRun}>
        <Play className="mr-2 h-3.5 w-3.5" />
        Run pipeline
      </Button>
    </HeroShell>
  );
}

function HeroShell({
  eyebrow,
  icon,
  title,
  body,
  children,
}: {
  eyebrow: string;
  icon: React.ReactNode;
  title: string;
  body: string;
  children: React.ReactNode;
}) {
  return (
    <Panel className="relative flex h-full flex-col justify-between overflow-hidden p-6">
      <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full accent-gradient opacity-[0.06] blur-2xl" />
      <div className="relative">
        <div className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent1/10">
            {icon}
          </span>
          <span className="eyebrow">{eyebrow}</span>
        </div>
        <h2 className="mt-4 max-w-lg font-display text-2xl leading-tight text-foreground">
          {title}
        </h2>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">{body}</p>
      </div>
      <div className="relative mt-6 flex flex-wrap items-center gap-2">{children}</div>
    </Panel>
  );
}
