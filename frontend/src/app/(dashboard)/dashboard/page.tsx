"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Send,
  Loader2,
  RefreshCw,
  Sparkles,
  CheckCircle2,
  Search,
  Square,
  Play,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { QuotaCard } from "@/components/dashboard/quota-card";
import { CreditsPill } from "@/components/dashboard/credits-pill";
import { MatchesStrip } from "@/components/dashboard/matches-strip";
import { ApplicationsList } from "@/components/dashboard/applications-list";
import { RunPipelineDialog } from "@/components/pipeline/run-pipeline-dialog";
import { SendApprovedButton } from "@/components/pipeline/send-approved-button";
import { usePipelineStatus } from "@/lib/use-pipeline-status";
import { deriveQuota, quotaFromApi, type OutreachQuota } from "@/lib/quota";
import { fadeInUp } from "@/lib/motion";
import { api, type Lead, type Stats, type MatchedJob } from "@/lib/api";

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
  const [query, setQuery] = useState("");

  const { state, abort, aborting } = usePipelineStatus();
  const running = state?.running ?? false;

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [s, l] = await Promise.all([api.stats.get(), api.leads.list()]);
      setStats(s);
      setLeads(l);
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

  const pendingReview = (stats?.pending_review ?? 0) + (stats?.in_review ?? 0);

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

  const filteredLeads = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return leads;
    return leads.filter((l) =>
      `${l.company} ${l.role} ${l.x_handle}`.toLowerCase().includes(q)
    );
  }, [leads, query]);

  return (
    <PageTransition>
      <Header
        title="Dashboard"
        description="Your outreach at a glance — and what to do next"
        action={
          <>
            {quota && <CreditsPill quota={quota} />}
            <div className="hidden items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 shadow-card sm:flex">
              <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search roles, companies…"
                className="w-44 bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
              />
            </div>
            <Button variant="outline" size="sm" onClick={load} disabled={loading}>
              <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
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
          {/* ROW 1 — the single most important next step + the metered resource */}
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

          {/* ROW 2 — top 5 matches, interactive tinted cards */}
          {matches.length > 0 && <MatchesStrip jobs={matches} />}

          {/* ROW 3 — all applications */}
          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <ApplicationsList leads={filteredLeads} />
          </motion.div>
        </div>
      )}

      <RunPipelineDialog open={runOpen} onOpenChange={setRunOpen} />
    </PageTransition>
  );
}

/**
 * NextAction — the command-center hero. Surfaces the single most important
 * next step so the user can act without navigating away.
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
