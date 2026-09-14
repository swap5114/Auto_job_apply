"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sparkles,
  Building2,
  MapPin,
  ExternalLink,
  CheckCircle2,
  Loader2,
  RefreshCw,
  ArrowRight,
  Flame,
} from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import { staggerContainer, fadeInUp, scaleIn } from "@/lib/motion";
import { api, type MatchedJob } from "@/lib/api";
import { Panel } from "@/components/ui/panel";

export default function MatchesPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<MatchedJob[]>([]);
  const [hasCriteria, setHasCriteria] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [matched, criteria] = await Promise.all([
        api.jobs.matched(),
        api.profile.getSearchCriteria().catch(() => null),
      ]);
      setJobs(matched);
      setHasCriteria(!!criteria);
    } catch (e: any) {
      setError(e?.message || "Failed to load matched jobs");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const topScore = useMemo(
    () => (jobs.length ? Math.max(...jobs.map((j) => j.match_score)) : 0),
    [jobs]
  );
  const savedCount = useMemo(
    () => jobs.filter((j) => j.already_saved_lead_id).length,
    [jobs]
  );

  async function handleSave(job: MatchedJob) {
    setSavingId(job.id);
    try {
      const lead = await api.jobs.save(job.id);
      setJobs((prev) =>
        prev.map((j) =>
          j.id === job.id
            ? { ...j, already_saved_lead_id: lead.id, already_saved_channel: lead.channel }
            : j
        )
      );
      toast.success(`Saved ${job.company_name} to your pipeline`, {
        action: {
          label: "View",
          onClick: () => router.push(`/leads?lead=${lead.id}`),
        },
      });
    } catch (e: any) {
      toast.error(e?.message || "Couldn't save this job");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <PageTransition>
      <Header
        title="Matched Jobs"
        description={
          jobs.length > 0
            ? `${jobs.length} role${jobs.length === 1 ? "" : "s"} matched to your profile — save the ones worth pursuing.`
            : "Real, ranked matches from the shared job catalog, based on your saved profile."
        }
        action={
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        }
      />

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error} — is the API running on port 8000?
        </div>
      )}

      {loading ? (
        <LoadingSkeleton />
      ) : !hasCriteria ? (
        <NoCriteriaState />
      ) : jobs.length === 0 ? (
        <NoMatchesState onRefresh={load} />
      ) : (
        <div className="space-y-6 pb-16">
          {/* Stats strip — the "wow" moment: real numbers, immediately */}
          <motion.div
            className="grid grid-cols-2 gap-4 sm:grid-cols-3"
            variants={staggerContainer(0.07)}
            initial="hidden"
            animate="show"
          >
            <motion.div variants={scaleIn}>
              <Panel className="p-5">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Sparkles className="h-3.5 w-3.5" />
                  <span className="text-xs font-medium">Matched Roles</span>
                </div>
                <AnimatedCounter
                  value={jobs.length}
                  className="mt-3 font-display text-[2rem] leading-none tabular-nums text-foreground"
                />
              </Panel>
            </motion.div>
            <motion.div variants={scaleIn}>
              <Panel className="p-5">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Flame className="h-3.5 w-3.5" />
                  <span className="text-xs font-medium">Best Match Signals</span>
                </div>
                <AnimatedCounter
                  value={topScore}
                  className="mt-3 font-display text-[2rem] leading-none tabular-nums text-foreground"
                />
              </Panel>
            </motion.div>
            <motion.div variants={scaleIn} className="col-span-2 sm:col-span-1">
              <Panel className="p-5">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span className="text-xs font-medium">Already Saved</span>
                </div>
                <AnimatedCounter
                  value={savedCount}
                  className="mt-3 font-display text-[2rem] leading-none tabular-nums text-foreground"
                />
              </Panel>
            </motion.div>
          </motion.div>

          {/* Match cards */}
          <motion.div
            className="grid gap-4 md:grid-cols-2"
            variants={staggerContainer(0.05, 0.1)}
            initial="hidden"
            animate="show"
          >
            <AnimatePresence>
              {jobs.map((job) => {
                const saved = !!job.already_saved_lead_id;
                const busy = savingId === job.id;

                return (
                  <motion.div key={job.id} variants={fadeInUp} layout>
                    <Panel className="flex h-full flex-col p-5">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-3">
                          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted font-display text-sm text-muted-foreground">
                            {job.company_name.charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <p className="text-sm font-semibold text-foreground">{job.company_name}</p>
                            <p className="text-sm text-muted-foreground">{job.title}</p>
                          </div>
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5 rounded-full bg-accent1/10 px-2.5 py-1">
                          <Flame className="h-3 w-3 text-accent1" />
                          <span className="text-xs font-semibold text-accent1">
                            {job.match_score} match{job.match_score === 1 ? "" : "es"}
                          </span>
                        </div>
                      </div>

                      {(job.location || job.department) && (
                        <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                          <MapPin className="h-3 w-3" />
                          {[job.location, job.department].filter(Boolean).join(" · ")}
                        </div>
                      )}

                      {job.matched_signals.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          {job.matched_signals.map((signal) => (
                            <Badge key={signal} variant="outline" className="text-[11px] capitalize">
                              {signal}
                            </Badge>
                          ))}
                        </div>
                      )}

                      {job.jd_text && (
                        <p className="mt-3 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                          {job.jd_text}
                        </p>
                      )}

                      <div className="mt-4 flex flex-1 items-end justify-between gap-3 pt-2">
                        <div className="flex items-center gap-2">
                          {job.apply_url && (
                            <Button variant="ghost" size="icon" asChild className="h-8 w-8">
                              <a href={job.apply_url} target="_blank" rel="noopener noreferrer" title="View listing">
                                <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
                              </a>
                            </Button>
                          )}
                          <Badge variant="secondary" className="text-[10px] capitalize">
                            {job.source}
                          </Badge>
                        </div>

                        {saved ? (
                          <Button
                            size="sm"
                            variant="outline"
                            className="border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                            onClick={() => router.push(`/leads?lead=${job.already_saved_lead_id}`)}
                          >
                            <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
                            Saved — View
                            <ArrowRight className="ml-1.5 h-3 w-3" />
                          </Button>
                        ) : (
                          <Button size="sm" disabled={busy} onClick={() => handleSave(job)}>
                            {busy ? (
                              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                            ) : null}
                            Save to pipeline
                          </Button>
                        )}
                      </div>
                    </Panel>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </motion.div>
        </div>
      )}
    </PageTransition>
  );
}

// ---------------------------------------------------------------------------
// Empty / loading states
// ---------------------------------------------------------------------------

function LoadingSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="rounded-2xl border border-border/70 bg-card p-5 shadow-card">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 animate-pulse rounded-xl bg-muted" />
            <div className="space-y-2">
              <div className="h-3.5 w-32 animate-pulse rounded bg-muted" />
              <div className="h-3 w-24 animate-pulse rounded bg-muted" />
            </div>
          </div>
          <div className="mt-4 h-3 w-full animate-pulse rounded bg-muted" />
          <div className="mt-2 h-3 w-2/3 animate-pulse rounded bg-muted" />
          <div className="mt-5 flex justify-end">
            <div className="h-8 w-20 animate-pulse rounded-lg bg-muted" />
          </div>
        </div>
      ))}
    </div>
  );
}

function NoCriteriaState() {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      className="flex flex-col items-center justify-center rounded-2xl border border-dashed py-24 text-center"
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full accent-gradient">
        <Sparkles className="h-7 w-7 text-white" />
      </div>
      <h3 className="mt-4 font-display text-xl text-foreground">Let&apos;s find your matches</h3>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">
        Add your target roles and tech stack on your profile (or upload a resume) and we&apos;ll
        match you against every job in the catalog instantly.
      </p>
      <Button asChild className="mt-5">
        <Link href="/profile">
          Set up your profile
          <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
        </Link>
      </Button>
    </motion.div>
  );
}

function NoMatchesState({ onRefresh }: { onRefresh: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      className="flex flex-col items-center justify-center rounded-2xl border border-dashed py-24 text-center"
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted">
        <Building2 className="h-7 w-7 text-muted-foreground" />
      </div>
      <h3 className="mt-4 font-display text-xl text-foreground">No matches yet</h3>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">
        Nothing in the catalog matches your current roles/tech stack. Try broadening your
        criteria, or check back after the next catalog refresh.
      </p>
      <div className="mt-5 flex gap-2">
        <Button variant="outline" onClick={onRefresh}>
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
          Refresh
        </Button>
        <Button asChild>
          <Link href="/profile">
            Edit criteria
            <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
          </Link>
        </Button>
      </div>
    </motion.div>
  );
}
