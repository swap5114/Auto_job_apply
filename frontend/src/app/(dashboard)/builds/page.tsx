"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Hammer, Loader2, RefreshCw, ChevronRight, ExternalLink, Terminal } from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { ResultCard, DeployStatusCard } from "@/components/leads/demo-builder";
import { staggerContainer, slideInLeft } from "@/lib/motion";
import { api, type DemoBuildSummary, type DemoBuildStatus } from "@/lib/api";

const ACTIVE_DEPLOY_STAGES = new Set([
  "exporting", "pushing_github", "deploying_vercel", "deploying_render",
]);

// How often to poll a single open build's status in the detail Sheet.
const DETAIL_POLL_MS = 3000;

/**
 * Detail view for one build, fetched directly by build_id via
 * GET /api/leads/{lead_id}/build-demo/{build_id} — independent of
 * research_company(), so it always shows the actual stored deploy result
 * (repo/frontend/backend URLs, failure reason) rather than requiring the
 * lead's research to be re-run (which would show a DIFFERENT, unrelated
 * demo idea, not this build's own result).
 */
function BuildDetailSheet({
  leadId,
  buildId,
  onOpenChange,
}: {
  leadId: string;
  buildId: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const [status, setStatus] = useState<DemoBuildStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!buildId) return;
    setLoading(true);
    setStatus(null);

    async function poll() {
      try {
        const s = await api.leads.getBuild(leadId, buildId!);
        setStatus(s);
        const buildActive = s.stage === "pending" || s.stage === "building";
        const deployActive = s.stage === "success" && s.deploy_stage != null && ACTIVE_DEPLOY_STAGES.has(s.deploy_stage);
        if (buildActive || deployActive) {
          pollRef.current = setTimeout(poll, DETAIL_POLL_MS);
        }
      } catch (e: any) {
        toast.error(e?.message || "Failed to load build details");
      } finally {
        setLoading(false);
      }
    }
    poll();

    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [leadId, buildId]);

  async function handleRetryDeploy() {
    if (!buildId) return;
    setRetrying(true);
    try {
      const s = await api.leads.retryDeploy(leadId, buildId);
      setStatus(s);
      toast.success("Retrying deploy…");
      pollRef.current = setTimeout(async function poll() {
        const updated = await api.leads.getBuild(leadId, buildId);
        setStatus(updated);
        const deployActive = updated.stage === "success" && updated.deploy_stage != null && ACTIVE_DEPLOY_STAGES.has(updated.deploy_stage);
        if (deployActive) pollRef.current = setTimeout(poll, DETAIL_POLL_MS);
      }, DETAIL_POLL_MS);
    } catch (e: any) {
      toast.error(e?.message || "Failed to retry deploy");
    } finally {
      setRetrying(false);
    }
  }

  return (
    <Sheet open={!!buildId} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        {buildId && (
          <>
            <SheetHeader>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Terminal className="h-3.5 w-3.5" />
                <span className="font-mono">{buildId}</span>
              </div>
              <SheetTitle className="font-display text-2xl">
                {status?.result?.entry_point ? "Build Details" : "Build Details"}
              </SheetTitle>
              <SheetDescription>
                {status ? `Attempt ${status.attempt}/${status.max_attempts}` : "Loading…"}
              </SheetDescription>
            </SheetHeader>

            <div className="mt-6 space-y-4">
              {loading && !status ? (
                <div className="flex items-center justify-center py-16 text-muted-foreground">
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                  Loading build…
                </div>
              ) : status ? (
                <>
                  {(status.stage === "pending" || status.stage === "building") && (
                    <div className="flex items-center gap-2 rounded-xl border bg-muted/20 p-4 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin text-accent1" />
                      {status.stage === "pending" ? "Spinning up sandbox…" : "Kiro is building this demo…"}
                    </div>
                  )}

                  {(status.stage === "success" || status.stage === "failed") && (
                    <>
                      <ResultCard result={status.result} error={status.error} />
                      {status.stage === "success" && (
                        <DeployStatusCard status={status} onRetryDeploy={handleRetryDeploy} retrying={retrying} />
                      )}
                    </>
                  )}

                  {status.stage === "needs_secrets" && (
                    <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-700">
                      This build is paused waiting for secrets. Open the lead's Research tab to provide them.
                    </div>
                  )}
                </>
              ) : null}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

type BadgeVariant = "new" | "review" | "approved" | "sent" | "rejected";

/**
 * Combines the sandbox build stage AND the deploy sub-stage into a single
 * display label. `stage === "success"` on its own only means the sandbox
 * build passed — it says nothing about whether GitHub/Vercel/Render deploys
 * finished, so those need to be checked separately (via deploy_stage) to
 * avoid mislabeling a build that's still deploying (or failed to deploy)
 * as simply "Deployed".
 */
function describeBuild(b: DemoBuildSummary): { label: string; dot: string; variant: BadgeVariant } {
  if (b.stage === "pending") return { label: "Starting", dot: "bg-amber-500", variant: "review" };
  if (b.stage === "building") return { label: "Building", dot: "bg-accent1", variant: "review" };
  if (b.stage === "needs_secrets") return { label: "Needs input", dot: "bg-amber-500", variant: "review" };
  if (b.stage === "failed") return { label: "Build failed", dot: "bg-red-500", variant: "rejected" };

  // stage === "success" from here — sandbox build passed, check deploy_stage
  switch (b.deploy_stage) {
    case "exporting":
      return { label: "Exporting files", dot: "bg-accent1", variant: "review" };
    case "pushing_github":
      return { label: "Pushing to GitHub", dot: "bg-accent1", variant: "review" };
    case "deploying_vercel":
      return { label: "Deploying frontend", dot: "bg-accent1", variant: "review" };
    case "deploying_render":
      return { label: "Deploying backend", dot: "bg-accent1", variant: "review" };
    case "deployed":
      return { label: "Deployed", dot: "bg-emerald-500", variant: "sent" };
    case "deploy_failed":
      return { label: "Deploy failed", dot: "bg-red-500", variant: "rejected" };
    default:
      // Sandbox succeeded but deploy hasn't started yet (rare timing window)
      return { label: "Verified", dot: "bg-emerald-500", variant: "approved" };
  }
}

// Polls faster while any build is actively running, slower when everything
// is idle — same idea as the pipeline-context poller elsewhere in the app,
// just scoped to this page rather than shared app-wide.
const ACTIVE_POLL_MS = 3000;
const IDLE_POLL_MS = 15000;

export default function BuildsPage() {
  const [builds, setBuilds] = useState<DemoBuildSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ leadId: string; buildId: string } | null>(null);

  async function load() {
    try {
      const data = await api.builds.list();
      setBuilds(data);
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Failed to load builds");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      await load();
      const anyActive = builds.some((b) => b.running);
      timer = setTimeout(tick, anyActive ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    }
    timer = setTimeout(tick, ACTIVE_POLL_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <PageTransition>
      <Header
        title="Builds"
        description="Demo projects built and deployed via the sandbox"
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
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Loading builds…
        </div>
      ) : builds.length === 0 ? (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex flex-col items-center justify-center rounded-2xl border border-dashed py-24"
        >
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted">
            <Hammer className="h-7 w-7 text-muted-foreground" />
          </div>
          <h3 className="mt-4 font-display text-xl text-foreground">No builds yet</h3>
          <p className="mt-1 max-w-sm text-center text-sm text-muted-foreground">
            Start one from a lead's Research tab — approve a demo project idea and click
            &quot;Build This Demo&quot;.
          </p>
          <Link href="/leads">
            <Button size="sm" className="mt-4">
              Go to Leads
            </Button>
          </Link>
        </motion.div>
      ) : (
        <div className="overflow-hidden rounded-2xl border bg-card shadow-elevation-low">
          <table className="w-full">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Demo</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Company</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Status</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Links</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Attempt</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Started</th>
                <th className="w-10 px-5 py-3" />
              </tr>
            </thead>
            <motion.tbody variants={staggerContainer(0.04)} initial="hidden" animate="show">
              <AnimatePresence mode="popLayout">
                {builds.map((b) => {
                  const { label, dot, variant } = describeBuild(b);
                  return (
                    <motion.tr
                      key={b.build_id}
                      variants={slideInLeft}
                      layout
                      className="group cursor-pointer border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                      onClick={() => setSelected({ leadId: b.lead_id, buildId: b.build_id })}
                    >
                      <td className="px-5 py-3.5">
                        <p className="text-sm font-medium text-foreground">
                          {b.demo_title || "Untitled demo"}
                        </p>
                        <p className="font-mono text-xs text-muted-foreground">{b.build_id}</p>
                      </td>
                      <td className="px-5 py-3.5 text-sm text-muted-foreground">{b.company || "—"}</td>
                      <td className="px-5 py-3.5">
                        <span className="inline-flex items-center gap-1.5">
                          <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
                          <Badge variant={variant}>{label}</Badge>
                          {b.running && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
                        </span>
                      </td>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-2">
                          {b.frontend_url && (
                            <a
                              href={b.frontend_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="inline-flex items-center gap-1 text-xs text-accent1 hover:underline"
                              title={b.frontend_url}
                            >
                              <ExternalLink className="h-3 w-3" /> Live
                            </a>
                          )}
                          {b.backend_url && (
                            <a
                              href={b.backend_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="inline-flex items-center gap-1 text-xs text-accent1 hover:underline"
                              title={b.backend_url}
                            >
                              <ExternalLink className="h-3 w-3" /> API
                            </a>
                          )}
                          {!b.frontend_url && !b.backend_url && (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </div>
                      </td>
                      <td className="px-5 py-3.5 text-sm text-muted-foreground">
                        {b.attempt}/{b.max_attempts}
                      </td>
                      <td className="px-5 py-3.5 text-sm text-muted-foreground">
                        {b.started_at ? new Date(b.started_at).toLocaleString() : "—"}
                      </td>
                      <td className="px-5 py-3.5">
                        <ChevronRight className="h-4 w-4 text-muted-foreground/40 transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
                      </td>
                    </motion.tr>
                  );
                })}
              </AnimatePresence>
            </motion.tbody>
          </table>
        </div>
      )}

      <BuildDetailSheet
        leadId={selected?.leadId ?? ""}
        buildId={selected?.buildId ?? null}
        onOpenChange={(open) => !open && setSelected(null)}
      />
    </PageTransition>
  );
}
