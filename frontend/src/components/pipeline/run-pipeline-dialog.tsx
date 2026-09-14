"use client";

import { useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import {
  Play,
  Loader2,
  Rocket,
  Upload,
  CheckCircle2,
  XCircle,
  Square,
  RotateCcw,
  Radar,
  Mail,
  FileText,
  PenLine,
  Inbox,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type PipelineStep } from "@/lib/api";
import { usePipelineStatus } from "@/lib/use-pipeline-status";

type SourceKey = "yc";

const SOURCES: { key: SourceKey; label: string; desc: string; icon: typeof Rocket }[] = [
  { key: "yc", label: "Y Combinator Startups", desc: "Active hiring YC startups catalog (v1 focus)", icon: Rocket },
];

// Friendly stage pipeline. Each stage matches one or more raw backend step
// names (state.steps[].step) so we can render animated boxes from live state.
const STAGES: { key: string; label: string; icon: typeof Radar; match: (s: string) => boolean }[] = [
  { key: "scrape", label: "Source", icon: Radar, match: (s) => s.startsWith("scrape") },
  { key: "email", label: "Find emails", icon: Mail, match: (s) => s.includes("contact") || s.includes("email") },
  { key: "tailor", label: "Tailor", icon: FileText, match: (s) => s.includes("tailor") || s.includes("resume") },
  { key: "draft", label: "Draft", icon: PenLine, match: (s) => s.includes("draft") || s.includes("outreach") },
  { key: "queue", label: "Queue", icon: Inbox, match: (s) => s.includes("feed") || s.includes("graph") || s.includes("queue") },
];

type StageStatus = "pending" | "active" | "done" | "error";

/** Resolve each friendly stage's status from the raw backend steps. */
function resolveStageStatuses(steps: PipelineStep[] | undefined, running: boolean): StageStatus[] {
  const list = steps ?? [];
  return STAGES.map((stage) => {
    const hits = list.filter((s) => stage.match(s.step));
    if (hits.length === 0) return running ? "pending" : "pending";
    if (hits.some((h) => h.status === "error")) return "error";
    if (hits.some((h) => h.status === "running")) return "active";
    if (hits.every((h) => h.status === "ok")) return "done";
    return "active";
  });
}

export function RunPipelineDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [selected, setSelected] = useState<Record<SourceKey, boolean>>({
    yc: true,
  });
  const [ycMax, setYcMax] = useState(5);
  const [starting, setStarting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);

  const { state, refresh, abort, aborting } = usePipelineStatus();
  const running = state?.running ?? false;
  const finished = !running && !!state?.finished_at;

  async function handleAbort() {
    try {
      await abort();
      toast.success("Run aborted");
    } catch (e: any) {
      toast.error(e?.message || "Failed to abort run");
    }
  }

  function toggle(key: SourceKey) {
    setSelected((s) => ({ ...s, [key]: !s[key] }));
  }

  async function handleRun() {
    const sources = (Object.keys(selected) as SourceKey[]).filter((k) => selected[k]);
    if (sources.length === 0) {
      toast.error("Pick at least one source");
      return;
    }
    setStarting(true);
    try {
      await api.pipeline.run({ sources, yc_max_leads: ycMax });
      toast.success("Pipeline started");
      await refresh();
    } catch (e: any) {
      toast.error(e?.message || "Failed to start pipeline");
    } finally {
      setStarting(false);
    }
  }

  async function handleCsv(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await api.pipeline.uploadCsv(file);
      toast.success(`Uploaded ${res.filename} — company scraping started`);
      await refresh();
    } catch (err: any) {
      toast.error(err?.message || "CSV upload failed");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <p className="eyebrow">Pipeline</p>
          <DialogTitle className="font-display text-2xl">Run the pipeline</DialogTitle>
          <DialogDescription>
            Sources are scraped, then Outra finds emails, tailors your resume, drafts
            outreach, and queues everything for review. Nothing sends without your approval.
          </DialogDescription>
        </DialogHeader>

        {/* Source selection */}
        <div className="space-y-2">
          {SOURCES.map((s) => {
            const active = selected[s.key];
            return (
              <button
                key={s.key}
                onClick={() => toggle(s.key)}
                disabled={running}
                className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-colors disabled:opacity-60 ${active ? "border-accent1/50 bg-accent1/5" : "border-border hover:bg-muted/40"
                  }`}
              >
                <div
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${active ? "accent-gradient text-white" : "bg-muted text-muted-foreground"
                    }`}
                >
                  <s.icon className="h-4 w-4" />
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-foreground">{s.label}</p>
                  <p className="text-xs text-muted-foreground">{s.desc}</p>
                </div>
                <span className="text-xs font-medium text-muted-foreground">
                  up to
                </span>
                <Input
                  type="number"
                  value={ycMax}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => setYcMax(Number(e.target.value))}
                  min={1}
                  max={15}
                  className="h-8 w-16"
                  disabled={running}
                />
              </button>
            );
          })}
        </div>

        {/* Animated stage pipeline — the redesigned centerpiece */}
        <StagePipeline steps={state?.steps} running={running} finished={finished} />

        {/* Run summary line (after a finished run) */}
        <AnimatePresence>
          {finished && state?.summary && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800"
            >
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
              Last run finished — {state.summary.ok} ok, {state.summary.failed} failed. New leads are
              queued for your review.
            </motion.div>
          )}
        </AnimatePresence>

        {/* Actions */}
        <div className="flex items-center justify-between gap-3 pt-1">
          {/* CSV upload */}
          <div>
            <input
              ref={fileInput}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={handleCsv}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInput.current?.click()}
              disabled={running || uploading}
            >
              {uploading ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Upload className="mr-1.5 h-3.5 w-3.5" />
              )}
              Upload CSV
            </Button>
          </div>

          <div className="flex items-center gap-2">
            {running ? (
              <>
                {/* Abort the in-progress run */}
                <Button variant="outline" onClick={handleAbort} disabled={aborting}>
                  {aborting ? (
                    <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Square className="mr-2 h-3 w-3 fill-current text-destructive" />
                  )}
                  {aborting ? "Aborting…" : "Abort"}
                </Button>
                <Button disabled>
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  Running…
                </Button>
              </>
            ) : (
              <Button onClick={handleRun} disabled={starting}>
                {starting ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : finished ? (
                  <RotateCcw className="mr-2 h-3.5 w-3.5" />
                ) : (
                  <Play className="mr-2 h-3.5 w-3.5" />
                )}
                {finished ? "Run again" : "Run Pipeline"}
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * StagePipeline — animated stage boxes that reflect the live run. Each box
 * moves through pending → active (pulsing ring) → done/error, with the
 * connectors filling as progress advances. Idle state shows the plan.
 */
function StagePipeline({
  steps,
  running,
  finished,
}: {
  steps: PipelineStep[] | undefined;
  running: boolean;
  finished: boolean;
}) {
  const statuses = resolveStageStatuses(steps, running);
  const idle = !running && !finished;

  return (
    <div className="rounded-2xl border border-border/70 bg-muted/20 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="eyebrow">{running ? "Running now" : finished ? "Last run" : "What happens"}</span>
        {running && (
          <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-accent1">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent1 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent1" />
            </span>
            Live
          </span>
        )}
      </div>

      <div className="flex items-stretch gap-1.5">
        {STAGES.map((stage, i) => {
          const status: StageStatus = idle ? "pending" : statuses[i];
          return (
            <div key={stage.key} className="flex flex-1 items-center gap-1.5">
              <StageBox stage={stage} status={status} index={i} />
              {i < STAGES.length - 1 && (
                <div className="relative h-px w-3 shrink-0 overflow-hidden rounded-full bg-border">
                  <motion.div
                    className="absolute inset-y-0 left-0 accent-gradient"
                    initial={{ width: 0 }}
                    animate={{ width: status === "done" ? "100%" : "0%" }}
                    transition={{ duration: 0.4 }}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StageBox({
  stage,
  status,
  index,
}: {
  stage: { label: string; icon: typeof Radar };
  status: StageStatus;
  index: number;
}) {
  const Icon = stage.icon;
  const styles: Record<StageStatus, string> = {
    pending: "border-border bg-card text-muted-foreground",
    active: "border-accent1/50 bg-accent1/5 text-accent1",
    done: "border-emerald-200 bg-emerald-50 text-emerald-600",
    error: "border-red-200 bg-red-50 text-red-500",
  };
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.03 * index }}
      className={`relative flex flex-1 flex-col items-center gap-1.5 rounded-xl border p-2.5 text-center transition-colors ${styles[status]}`}
    >
      {status === "active" && (
        <span className="pointer-events-none absolute inset-0 rounded-xl ring-2 ring-accent1/30 animate-pulse" />
      )}
      <span className="relative flex h-7 w-7 items-center justify-center">
        {status === "done" ? (
          <CheckCircle2 className="h-4 w-4" />
        ) : status === "error" ? (
          <XCircle className="h-4 w-4" />
        ) : status === "active" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Icon className="h-4 w-4" />
        )}
      </span>
      <span className="text-[10px] font-medium leading-tight">{stage.label}</span>
    </motion.div>
  );
}

/**
 * Self-contained button that opens the RunPipelineDialog.
 * Drop-in for the dashboard, leads page, and topbar.
 */
export function RunPipelineButton({
  variant = "default",
  size = "sm",
  label = "Run Pipeline",
  className,
}: {
  variant?: "default" | "outline" | "ghost" | "secondary";
  size?: "default" | "sm" | "lg" | "icon";
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const { state } = usePipelineStatus();
  const running = state?.running ?? false;

  return (
    <>
      <Button variant={variant} size={size} className={className} onClick={() => setOpen(true)}>
        {running ? (
          <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
        ) : (
          <Play className="mr-2 h-3.5 w-3.5" />
        )}
        {running ? "Running…" : label}
      </Button>
      <RunPipelineDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
