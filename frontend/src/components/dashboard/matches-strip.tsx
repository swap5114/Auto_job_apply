"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import { Flame, ArrowRight, Loader2, CheckCircle2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Panel } from "@/components/ui/panel";
import { api, type MatchedJob } from "@/lib/api";
import { staggerContainer, fadeInUp } from "@/lib/motion";
import { useState } from "react";

/**
 * Top-5 matches strip for the dashboard — the "wow" surface. Compact cards
 * with company/role/fit and an inline Save so the user can act without
 * navigating to the full Matches page.
 */
export function MatchesStrip({ jobs: initial }: { jobs: MatchedJob[] }) {
  const router = useRouter();
  const [jobs, setJobs] = useState(initial.slice(0, 5));
  const [savingId, setSavingId] = useState<string | null>(null);

  async function handleSave(job: MatchedJob) {
    setSavingId(job.id);
    try {
      const lead = await api.jobs.save(job.id);
      setJobs((prev) =>
        prev.map((j) => (j.id === job.id ? { ...j, already_saved_lead_id: lead.id } : j))
      );
      toast.success(`Saved ${job.company_name} to your pipeline`);
    } catch (e: any) {
      toast.error(e?.message || "Failed to save");
    } finally {
      setSavingId(null);
    }
  }

  if (jobs.length === 0) return null;

  return (
    <div>
      <div className="mb-3 flex items-end justify-between">
        <div>
          <p className="eyebrow">Top matches</p>
          <h3 className="mt-1 text-sm font-semibold text-foreground">
            Roles that fit your profile
          </h3>
        </div>
        <Link href="/matches" className="text-xs font-medium text-accent1 hover:underline">
          View all matches →
        </Link>
      </div>

      <motion.div
        className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"
        variants={staggerContainer(0.05)}
        initial="hidden"
        animate="show"
      >
        {jobs.map((job) => {
          const saved = !!job.already_saved_lead_id;
          const busy = savingId === job.id;
          return (
            <motion.div key={job.id} variants={fadeInUp}>
              <Panel interactive className="flex h-full flex-col p-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted font-display text-xs text-muted-foreground">
                    {job.company_name.charAt(0).toUpperCase()}
                  </div>
                  <span className="inline-flex items-center gap-1 rounded-full bg-accent1/10 px-2 py-0.5 text-[10px] font-semibold text-accent1">
                    <Flame className="h-2.5 w-2.5" />
                    {job.match_score}
                  </span>
                </div>
                <p className="mt-3 truncate text-sm font-semibold text-foreground" title={job.company_name}>
                  {job.company_name}
                </p>
                <p className="line-clamp-2 text-xs leading-snug text-muted-foreground" title={job.title}>
                  {job.title}
                </p>

                <div className="mt-auto pt-3">
                  {saved ? (
                    <button
                      onClick={() => router.push(`/leads?lead=${job.already_saved_lead_id}`)}
                      className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 hover:underline"
                    >
                      <CheckCircle2 className="h-3 w-3" />
                      Saved
                      <ArrowRight className="h-3 w-3" />
                    </button>
                  ) : (
                    <button
                      onClick={() => handleSave(job)}
                      disabled={busy}
                      className="inline-flex items-center gap-1 text-xs font-medium text-accent1 hover:underline disabled:opacity-60"
                    >
                      {busy ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Sparkles className="h-3 w-3" />
                      )}
                      Save to pipeline
                    </button>
                  )}
                </div>
              </Panel>
            </motion.div>
          );
        })}
      </motion.div>
    </div>
  );
}
