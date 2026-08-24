"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Hammer,
  Loader2,
  Terminal,
  KeyRound,
  CheckCircle2,
  XCircle,
  RotateCcw,
  Copy,
  Github,
  ExternalLink,
  Rocket,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fadeInUp } from "@/lib/motion";
import { cn, stripAnsi, getActiveBuildId, setActiveBuildId, clearActiveBuildId } from "@/lib/utils";
import { api, type DemoProject, type DemoBuildStatus, type NeededSecret } from "@/lib/api";

// How often to poll build status. Builds are multi-minute (Kiro turns can
// each take tens of seconds), so this doesn't need to be aggressive — the
// pipeline-context poller elsewhere in this app uses a similar cadence.
const POLL_INTERVAL_MS = 3000;

type LocalStage = "idle" | "resuming" | DemoBuildStatus["stage"];

/**
 * Deploy stages that mean "still in progress, keep polling." Only
 * deploy_failed / deployed are terminal — everything else here is a step
 * along the way (export -> GitHub -> Vercel -> Render).
 */
const ACTIVE_DEPLOY_STAGES = new Set([
  "exporting", "pushing_github", "deploying_vercel", "deploying_render",
]);

function StageBadge({ stage, deployStage }: { stage: LocalStage; deployStage: string | null | undefined }) {
  const map: Record<LocalStage, { label: string; className: string }> = {
    idle: { label: "Not started", className: "bg-muted text-muted-foreground" },
    resuming: { label: "Checking…", className: "bg-muted text-muted-foreground" },
    pending: { label: "Starting…", className: "bg-amber-500/10 text-amber-600" },
    building: { label: "Building", className: "bg-accent1/10 text-accent1" },
    needs_secrets: { label: "Needs input", className: "bg-amber-500/10 text-amber-600" },
    success: { label: "Verified", className: "bg-emerald-500/10 text-emerald-600" },
    failed: { label: "Failed", className: "bg-red-500/10 text-red-600" },
  };

  // stage === "success" only means the SANDBOX build passed — overlay the
  // deploy sub-stage on top so this doesn't misleadingly say "Verified"
  // while a GitHub push or Vercel deploy is still (or failed to be) running.
  if (stage === "success" && deployStage) {
    const deployMap: Record<string, { label: string; className: string }> = {
      exporting: { label: "Exporting…", className: "bg-accent1/10 text-accent1" },
      pushing_github: { label: "Pushing to GitHub…", className: "bg-accent1/10 text-accent1" },
      deploying_vercel: { label: "Deploying frontend…", className: "bg-accent1/10 text-accent1" },
      deploying_render: { label: "Deploying backend…", className: "bg-accent1/10 text-accent1" },
      deployed: { label: "Deployed", className: "bg-emerald-500/10 text-emerald-600" },
      deploy_failed: { label: "Deploy failed", className: "bg-red-500/10 text-red-600" },
    };
    const override = deployMap[deployStage];
    if (override) {
      return (
        <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-medium", override.className)}>
          {override.label}
        </span>
      );
    }
  }

  const { label, className } = map[stage];
  return (
    <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-medium", className)}>
      {label}
    </span>
  );
}

/**
 * Live terminal-style log viewer. Auto-scrolls to the bottom as new output
 * arrives, unless the user has manually scrolled up to read something —
 * in which case we don't yank them back down.
 */
function LogViewer({ text }: { text: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && !userScrolledUp.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [text]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    userScrolledUp.current = !atBottom;
  }

  const clean = stripAnsi(text).trim();

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="max-h-48 overflow-y-auto rounded-lg bg-[#0b0d10] p-3 font-mono text-[11px] leading-relaxed text-[#c9d1d9]"
    >
      {clean ? (
        <pre className="whitespace-pre-wrap">{clean}</pre>
      ) : (
        <span className="text-[#6e7681]">Waiting for output…</span>
      )}
    </div>
  );
}

/**
 * Form for supplying the secrets Kiro flagged as missing mid-build.
 * Renders one input per requested secret, all required before submit.
 */
function SecretsForm({
  needed,
  onSubmit,
  submitting,
}: {
  needed: NeededSecret[];
  onSubmit: (secrets: Record<string, string>) => void;
  submitting: boolean;
}) {
  const [values, setValues] = useState<Record<string, string>>({});

  const allFilled = needed.every((n) => (values[n.name] || "").trim().length > 0);

  return (
    <div className="space-y-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4 text-amber-600" />
        <span className="text-sm font-medium text-foreground">
          The build needs {needed.length === 1 ? "a value" : "some values"} to continue
        </span>
      </div>
      <div className="space-y-2.5">
        {needed.map((n) => (
          <div key={n.name}>
            <label className="mb-1 block font-mono text-xs font-medium text-foreground">
              {n.name}
            </label>
            <Input
              type="password"
              placeholder={n.why}
              value={values[n.name] || ""}
              onChange={(e) => setValues((v) => ({ ...v, [n.name]: e.target.value }))}
              className="h-9 text-sm"
              disabled={submitting}
            />
            <p className="mt-1 text-xs text-muted-foreground">{n.why}</p>
          </div>
        ))}
      </div>
      <Button
        size="sm"
        className="w-full"
        disabled={!allFilled || submitting}
        onClick={() => onSubmit(values)}
      >
        {submitting ? (
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
        ) : (
          <KeyRound className="mr-1.5 h-3.5 w-3.5" />
        )}
        Continue Build
      </Button>
      <p className="text-[11px] text-muted-foreground">
        These are written into the sandbox for this build only — they're never sent to GitHub or committed anywhere.
      </p>
    </div>
  );
}

export function ResultCard({ result, error }: { result: DemoBuildStatus["result"]; error: string | null }) {
  const failed = !result || result.status === "failed";

  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        failed ? "border-red-500/30 bg-red-500/5" : "border-emerald-500/30 bg-emerald-500/5"
      )}
    >
      <div className="mb-2 flex items-center gap-2">
        {failed ? (
          <XCircle className="h-4 w-4 text-red-600" />
        ) : (
          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
        )}
        <span className={cn("text-sm font-medium", failed ? "text-red-700" : "text-emerald-700")}>
          {failed ? "Build failed" : "Build succeeded"}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        {result?.summary || error || "No details available."}
      </p>
      {result?.entry_point && (
        <p className="mt-2 font-mono text-xs text-muted-foreground">
          Entry point: {result.entry_point}
        </p>
      )}
    </div>
  );
}

/**
 * Shows what's happening after the sandbox build succeeds: exporting files,
 * pushing to GitHub, deploying to Vercel/Render, and finally the live links.
 * `deploy_stage` is None only in the brief window between "sandbox build
 * succeeded" and "the deploy background thread has actually started" —
 * treated the same as "exporting" so there's no flash of an empty state.
 */
export function DeployStatusCard({
  status,
  onRetryDeploy,
  retrying,
}: {
  status: DemoBuildStatus;
  /** Optional — when provided, a "Retry Deploy" button renders on failure. */
  onRetryDeploy?: () => void;
  retrying?: boolean;
}) {
  const deployStage = status.deploy_stage ?? "exporting";

  if (deployStage === "deploy_failed") {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4">
        <div className="mb-1.5 flex items-center gap-2">
          <XCircle className="h-4 w-4 text-red-600" />
          <span className="text-sm font-medium text-red-700">Deployment failed</span>
        </div>
        <p className="text-sm text-muted-foreground">
          {status.deploy_error || "The build passed inside the sandbox, but pushing or deploying it failed."}
        </p>
        {status.repo_url && (
          <a
            href={status.repo_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center gap-1.5 text-xs text-accent1 hover:underline"
          >
            <Github className="h-3 w-3" /> Code was pushed to GitHub
          </a>
        )}
        {onRetryDeploy && (
          <Button size="sm" variant="outline" className="mt-3 w-full" onClick={onRetryDeploy} disabled={retrying}>
            {retrying ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
            )}
            Retry Deploy
          </Button>
        )}
      </div>
    );
  }

  if (deployStage === "deployed") {
    return (
      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
        <div className="mb-2 flex items-center gap-2">
          <Rocket className="h-4 w-4 text-emerald-600" />
          <span className="text-sm font-medium text-emerald-700">Deployed and live</span>
        </div>
        <div className="space-y-1.5">
          {status.repo_url && (
            <a
              href={status.repo_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-sm text-foreground hover:text-accent1"
            >
              <Github className="h-3.5 w-3.5 text-muted-foreground" />
              View source on GitHub
            </a>
          )}
          {status.frontend_url && (
            <a
              href={status.frontend_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-sm text-foreground hover:text-accent1"
            >
              <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
              Open live demo
            </a>
          )}
          {status.backend_url && (
            <a
              href={status.backend_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-sm text-foreground hover:text-accent1"
            >
              <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
              Open backend API
            </a>
          )}
        </div>
        {status.backend_url && (
          <p className="mt-2 text-[11px] text-muted-foreground">
            The backend is on Render's free tier — it spins down after 15 minutes idle, so the
            first request after a while may take up to a minute to wake it back up.
          </p>
        )}
      </div>
    );
  }

  // In-progress deploy sub-stages
  const labels: Record<string, string> = {
    exporting: "Exporting build files…",
    pushing_github: "Pushing to GitHub…",
    deploying_vercel: "Deploying frontend to Vercel…",
    deploying_render: "Deploying backend to Render…",
  };

  return (
    <div className="rounded-xl border bg-muted/20 p-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin text-accent1" />
        {labels[deployStage] || "Deploying…"}
      </div>
    </div>
  );
}

export function DemoBuilder({
  leadId,
  demoProject,
}: {
  leadId: string;
  // Optional: ResearchPanel renders this component even before research has
  // been run (specifically so a build that's already in progress from a
  // previous mount is still recoverable/visible). In that pre-research
  // state there's no demo_project to start a NEW build from — only
  // demoProject-less recovery of an existing one. handleStart is simply
  // never reachable in that case (the "Build This Demo" button doesn't
  // render without a demoProject; see the idle branch below).
  demoProject?: DemoProject;
}) {
  // "resuming" covers the brief window while we check localStorage + fetch
  // the current status of a possibly-still-running build for this lead,
  // before we know whether to show "idle" or the in-progress/done view.
  // Without this, there'd be a flash of the "Build This Demo" button on
  // every mount even when a build is actively running in the background.
  const [stage, setStage] = useState<LocalStage | "resuming">("resuming");
  const [buildId, setBuildId] = useState<string | null>(null);
  const [status, setStatus] = useState<DemoBuildStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [submittingSecrets, setSubmittingSecrets] = useState(false);
  const [retryingDeploy, setRetryingDeploy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // On mount, check whether a build was already started for this lead (from
  // a previous mount of this same component — e.g. the Sheet was closed and
  // reopened, or "Run Research" was re-run showing a different demo idea
  // while the earlier build kept running server-side). If one exists, fetch
  // its current status immediately and resume polling rather than showing
  // the idle "Build This Demo" button as if nothing had happened.
  useEffect(() => {
    const existingBuildId = getActiveBuildId(leadId);
    if (!existingBuildId) {
      setStage("idle");
      return;
    }

    setBuildId(existingBuildId);
    api.leads
      .buildDemoStatus(leadId, existingBuildId)
      .then((s) => {
        setStatus(s);
        setStage(s.stage);
        const buildActive = s.stage === "pending" || s.stage === "building";
        const deployActive = s.stage === "success" && s.deploy_stage != null && ACTIVE_DEPLOY_STAGES.has(s.deploy_stage);
        if (buildActive || deployActive) {
          schedulePoll(existingBuildId);
        }
      })
      .catch(() => {
        // The build_id we had saved no longer exists server-side — most
        // likely the API process restarted (in-memory registry wiped) since
        // the build was started. Nothing to resume; clear the stale
        // reference so we don't keep trying on every future mount.
        clearActiveBuildId(leadId);
        setBuildId(null);
        setStage("idle");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leadId]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, []);

  function schedulePoll(id: string) {
    if (pollRef.current) clearTimeout(pollRef.current);
    pollRef.current = setTimeout(() => poll(id), POLL_INTERVAL_MS);
  }

  async function poll(id: string) {
    try {
      const s = await api.leads.buildDemoStatus(leadId, id);
      setStatus(s);
      setStage(s.stage);
      // Keep polling while there's an active sandbox build OR an active
      // deploy sub-stage (export -> GitHub -> Vercel -> Render all happen
      // after stage flips to "success", so stage alone isn't enough to know
      // whether there's still work in flight). needs_secrets pauses polling
      // too, since nothing changes server-side until the user submits a value.
      const buildActive = s.stage === "pending" || s.stage === "building";
      const deployActive = s.stage === "success" && s.deploy_stage != null && ACTIVE_DEPLOY_STAGES.has(s.deploy_stage);
      if (buildActive || deployActive) {
        schedulePoll(id);
      } else {
        // Terminal state reached (success+deployed, success+deploy_failed,
        // or failed) — this build no longer needs to be recovered on a
        // future remount, so stop tracking it as "active" for this lead.
        clearActiveBuildId(leadId);
      }
    } catch (e: any) {
      toast.error(e?.message || "Lost connection to build status");
    }
  }

  async function handleStart() {
    // Guarded at the call site too (the "Build This Demo" button only
    // renders once research has produced a demo_project — see the idle
    // branch below), but this makes the invariant explicit for TypeScript
    // and safe against any future caller that forgets that precondition.
    if (!demoProject) return;
    setStarting(true);
    setStage("pending");
    try {
      const s = await api.leads.buildDemo(leadId, demoProject);
      setBuildId(s.build_id);
      setStatus(s);
      setStage(s.stage);
      setActiveBuildId(leadId, s.build_id);
      schedulePoll(s.build_id);
    } catch (e: any) {
      toast.error(e?.message || "Failed to start build");
      setStage("idle");
    } finally {
      setStarting(false);
    }
  }

  async function handleProvideSecrets(secrets: Record<string, string>) {
    if (!buildId) return;
    setSubmittingSecrets(true);
    try {
      const s = await api.leads.provideBuildSecrets(leadId, buildId, secrets);
      setStatus(s);
      setStage(s.stage);
      schedulePoll(buildId);
      toast.success("Secrets provided — build resuming");
    } catch (e: any) {
      toast.error(e?.message || "Failed to submit secrets");
    } finally {
      setSubmittingSecrets(false);
    }
  }

  async function handleCancel() {
    if (!buildId) return;
    try {
      await api.leads.cancelBuild(leadId, buildId);
      toast.success("Build cancelled");
      setStage("failed");
      clearActiveBuildId(leadId);
      if (pollRef.current) clearTimeout(pollRef.current);
    } catch (e: any) {
      toast.error(e?.message || "Failed to cancel build");
    }
  }

  function handleRetry() {
    clearActiveBuildId(leadId);
    setBuildId(null);
    setStatus(null);
    setStage("idle");
  }

  async function handleRetryDeploy() {
    if (!buildId) return;
    setRetryingDeploy(true);
    try {
      const s = await api.leads.retryDeploy(leadId, buildId);
      setStatus(s);
      setStage(s.stage);
      setActiveBuildId(leadId, buildId); // deploy is active again — make it recoverable
      schedulePoll(buildId);
      toast.success("Retrying deploy…");
    } catch (e: any) {
      toast.error(e?.message || "Failed to retry deploy");
    } finally {
      setRetryingDeploy(false);
    }
  }

  function copyBuildId() {
    if (!buildId) return;
    navigator.clipboard.writeText(buildId);
    toast.success("Build ID copied");
  }

  const isActive = stage === "pending" || stage === "building";

  if (stage === "resuming") {
    // Brief window while we check whether a build is already running for
    // this lead from a previous mount — avoid flashing "Build This Demo"
    // only to immediately replace it with the in-progress view a moment
    // later once the lookup resolves.
    return (
      <div className="mt-3 flex items-center gap-2 border-t border-accent1/20 pt-3 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Checking build status…
      </div>
    );
  }

  // In the idle state with no demo_project yet (DemoBuilder mounted before
  // research has been run — see ResearchPanel), there's nothing to build
  // and nothing to recover, so render nothing rather than a dead button.
  if (stage === "idle" && !demoProject) {
    return null;
  }

  return (
    <div className="mt-3 border-t border-accent1/20 pt-3">
      {stage === "idle" && demoProject && (
        <Button size="sm" className="w-full" onClick={handleStart} disabled={starting}>
          {starting ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Hammer className="mr-1.5 h-3.5 w-3.5" />
          )}
          Build This Demo
        </Button>
      )}

      <AnimatePresence mode="wait">
        {stage !== "idle" && (
          <motion.div
            key={stage}
            variants={fadeInUp}
            initial="hidden"
            animate="show"
            exit={{ opacity: 0 }}
            className="space-y-3"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Terminal className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">
                  {buildId ? (
                    <button
                      onClick={copyBuildId}
                      className="inline-flex items-center gap-1 font-mono hover:text-foreground"
                      title="Copy build ID"
                    >
                      {buildId} <Copy className="h-3 w-3" />
                    </button>
                  ) : (
                    "Starting…"
                  )}
                  {status && status.max_attempts > 1 && (
                    <span> · attempt {status.attempt}/{status.max_attempts}</span>
                  )}
                </span>
              </div>
              <StageBadge stage={stage} deployStage={status?.deploy_stage} />
            </div>

            {isActive && (
              <>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin text-accent1" />
                  {stage === "pending" ? "Spinning up sandbox…" : "Kiro is building your demo…"}
                </div>
                {status?.logs_tail && <LogViewer text={status.logs_tail} />}
                <Button variant="ghost" size="sm" className="w-full text-muted-foreground" onClick={handleCancel}>
                  Cancel build
                </Button>
              </>
            )}

            {stage === "needs_secrets" && status?.needs_secrets && (
              <>
                {status.logs_tail && <LogViewer text={status.logs_tail} />}
                <SecretsForm
                  needed={status.needs_secrets.needed}
                  onSubmit={handleProvideSecrets}
                  submitting={submittingSecrets}
                />
              </>
            )}

            {(stage === "success" || stage === "failed") && (
              <>
                <ResultCard result={status?.result ?? null} error={status?.error ?? null} />

                {stage === "success" && status && (
                  <DeployStatusCard status={status} onRetryDeploy={handleRetryDeploy} retrying={retryingDeploy} />
                )}

                <Button variant="outline" size="sm" className="w-full" onClick={handleRetry}>
                  <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                  {stage === "failed" ? "Try Again" : "Build Again"}
                </Button>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
