"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, Loader2, Check, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { api, type MatchedJob } from "@/lib/api";
import { staggerContainer, fadeInUp } from "@/lib/motion";

/**
 * Top-5 matches strip for the dashboard — the reference "wow" surface.
 *
 * Each match renders as a soft-tinted, fully interactive card carrying a
 * short company eyebrow, the role, and a fit badge (STRONG / GOOD / FAIR)
 * derived from the match score. Saving turns the catalog job into a
 * pipeline lead; removing deletes that lead so the card flips back to an
 * un-saved state.
 */

/** Rotating soft pastel tints, mirroring the reference cards. */
const TINTS = [
  {
    bg: "bg-[#fdf6e3]",
    ring: "ring-[#f0e4bf]",
    hoverRing: "hover:ring-[#e6d38f]",
    eyebrow: "text-[#a98b3c]",
  },
  {
    bg: "bg-[#eef7f0]",
    ring: "ring-[#cfe8d6]",
    hoverRing: "hover:ring-[#a9d6b6]",
    eyebrow: "text-[#4f9169]",
  },
  {
    bg: "bg-[#f4f5f7]",
    ring: "ring-[#e3e6ea]",
    hoverRing: "hover:ring-[#cbd1d9]",
    eyebrow: "text-[#7b8493]",
  },
  {
    bg: "bg-[#fdeeee]",
    ring: "ring-[#f6d7d7]",
    hoverRing: "hover:ring-[#eeb9b9]",
    eyebrow: "text-[#c17b7b]",
  },
  {
    bg: "bg-[#f1eefb]",
    ring: "ring-[#ddd4f3]",
    hoverRing: "hover:ring-[#c3b4ea]",
    eyebrow: "text-[#8672c0]",
  },
] as const;

/** Map a raw match score (count of matched signals) to a fit tier. */
function fitTier(score: number): { label: string; className: string } {
  if (score >= 4) return { label: "STRONG", className: "text-emerald-700" };
  if (score >= 2) return { label: "GOOD", className: "text-foreground/70" };
  return { label: "FAIR", className: "text-muted-foreground" };
}

/** A short, uppercase company codename for the eyebrow line. */
function companyEyebrow(name: string): string {
  return name.trim().toUpperCase();
}

export function MatchesStrip({ jobs: initial }: { jobs: MatchedJob[] }) {
  const router = useRouter();
  const [jobs, setJobs] = useState(initial.slice(0, 5));
  const [busyId, setBusyId] = useState<string | null>(null);

  async function handleSave(job: MatchedJob) {
    setBusyId(job.id);
    try {
      const lead = await api.jobs.save(job.id);
      setJobs((prev) =>
        prev.map((j) => (j.id === job.id ? { ...j, already_saved_lead_id: lead.id } : j))
      );
      toast.success(`Saved ${job.company_name} to your pipeline`, {
        action: {
          label: "View",
          onClick: () => router.push(`/leads?lead=${lead.id}`),
        },
      });
    } catch (e: any) {
      toast.error(e?.message || "Couldn't save this match");
    } finally {
      setBusyId(null);
    }
  }

  async function handleRemove(job: MatchedJob) {
    if (!job.already_saved_lead_id) return;
    setBusyId(job.id);
    try {
      await api.leads.remove(job.already_saved_lead_id);
      setJobs((prev) =>
        prev.map((j) => (j.id === job.id ? { ...j, already_saved_lead_id: null } : j))
      );
      toast.success(`Removed ${job.company_name} from your pipeline`);
    } catch (e: any) {
      toast.error(e?.message || "Couldn't remove this match");
    } finally {
      setBusyId(null);
    }
  }

  if (jobs.length === 0) return null;

  return (
    <section>
      <div className="mb-4 flex items-center justify-center">
        <h3 className="text-sm font-medium text-muted-foreground">Top job matches</h3>
      </div>

      <motion.div
        className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
        variants={staggerContainer(0.05)}
        initial="hidden"
        animate="show"
      >
        {jobs.slice(0, 4).map((job, i) => {
          const tint = TINTS[i % TINTS.length];
          const fit = fitTier(job.match_score);
          const saved = !!job.already_saved_lead_id;
          const busy = busyId === job.id;

          return (
            <motion.div key={job.id} variants={fadeInUp}>
              <div
                role="button"
                tabIndex={0}
                onClick={() =>
                  saved
                    ? router.push(`/leads?lead=${job.already_saved_lead_id}`)
                    : router.push("/matches")
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    saved
                      ? router.push(`/leads?lead=${job.already_saved_lead_id}`)
                      : router.push("/matches");
                  }
                }}
                className={cn(
                  "group relative flex h-full cursor-pointer flex-col rounded-2xl p-4 ring-1 transition-all duration-200",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent1",
                  tint.bg,
                  tint.ring,
                  tint.hoverRing,
                  "hover:-translate-y-0.5 hover:shadow-card-hover"
                )}
              >
                <p className={cn("truncate text-[10px] font-semibold tracking-[0.14em]", tint.eyebrow)} title={job.company_name}>
                  {companyEyebrow(job.company_name)}
                </p>

                <div className="mt-2 flex items-start justify-between gap-2">
                  <p className="line-clamp-2 text-sm font-semibold leading-snug text-foreground" title={job.title}>
                    {job.title}
                  </p>
                  <span className={cn("shrink-0 text-[10px] font-semibold tracking-wide", fit.className)}>
                    {fit.label}
                  </span>
                </div>

                {/* Save / remove control — appears on hover/focus, sits at the bottom */}
                <div className="mt-auto pt-4">
                  {saved ? (
                    <div className="flex items-center justify-between">
                      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700">
                        <Check className="h-3 w-3" />
                        In pipeline
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleRemove(job);
                        }}
                        disabled={busy}
                        title="Remove from pipeline"
                        className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-black/5 hover:text-destructive disabled:opacity-60"
                      >
                        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
                        Remove
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSave(job);
                      }}
                      disabled={busy}
                      className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-foreground/70 transition-colors hover:bg-black/5 hover:text-foreground disabled:opacity-60"
                    >
                      {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                      Save to pipeline
                    </button>
                  )}
                </div>
              </div>
            </motion.div>
          );
        })}

        {/* 5th slot: view-all tile so all 5 matches stay reachable */}
        <motion.div variants={fadeInUp} className="hidden xl:block">
          <Link
            href="/matches"
            className="group flex h-full flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-card/40 p-4 text-center transition-colors hover:border-accent1/50 hover:bg-accent1/5"
          >
            <span className="text-sm font-semibold text-foreground">
              {jobs.length > 4 ? `+${jobs.length - 4} more` : "All matches"}
            </span>
            <span className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-accent1">
              View all
              <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
            </span>
          </Link>
        </motion.div>
      </motion.div>
    </section>
  );
}
