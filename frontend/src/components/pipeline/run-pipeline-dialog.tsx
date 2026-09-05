"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import {
  Play,
  Loader2,
  Briefcase,
  Globe,
  Rocket,
  Twitter,
  Building2,
  Upload,
  CheckCircle2,
  XCircle,
  FileText,
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
import { api } from "@/lib/api";
import { usePipelineStatus } from "@/lib/use-pipeline-status";

type SourceKey = "yc";

const SOURCES: { key: SourceKey; label: string; desc: string; icon: typeof Rocket }[] = [
  { key: "yc", label: "Y Combinator Startups", desc: "Active hiring YC startups catalog (v1 focus)", icon: Rocket },
];

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

  const { state, refresh } = usePipelineStatus();
  const running = state?.running ?? false;

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
          <DialogTitle>Run Pipeline</DialogTitle>
          <DialogDescription>
            Pick sources to scrape. The pipeline then finds emails, tailors resumes,
            drafts outreach, and queues everything for your review. Nothing sends without approval.
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
                className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-colors disabled:opacity-60 ${
                  active ? "border-accent1/50 bg-accent1/5" : "border-border hover:bg-muted/40"
                }`}
              >
                <div
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                    active ? "accent-gradient text-white" : "bg-muted text-muted-foreground"
                  }`}
                >
                  <s.icon className="h-4 w-4" />
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-foreground">{s.label}</p>
                  <p className="text-xs text-muted-foreground">{s.desc}</p>
                </div>
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-md border ${
                    active ? "border-accent1 bg-accent1 text-white" : "border-border"
                  }`}
                >
                  {active && <CheckCircle2 className="h-3.5 w-3.5" />}
                </span>
              </button>
            );
          })}
        </div>

        {/* Caps for YC */}
        {selected.yc && (
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-muted-foreground">YC max leads per run</label>
            <Input
              type="number"
              value={ycMax}
              onChange={(e) => setYcMax(Number(e.target.value))}
              min={1}
              max={15}
              className="h-8 w-20"
              disabled={running}
            />
          </div>
        )}

        {/* Live progress */}
        {(running || (state?.steps?.length ?? 0) > 0) && (
          <div className="rounded-xl border bg-muted/20 p-3">
            <div className="mb-2 flex items-center gap-2 text-sm">
              {running ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin text-accent1" />
                  <span className="text-foreground">
                    Running{state?.current_step ? `: ${state.current_step}` : "…"}
                  </span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  <span className="text-foreground">
                    Last run finished
                    {state?.summary ? ` — ${state.summary.ok} ok, ${state.summary.failed} failed` : ""}
                  </span>
                </>
              )}
            </div>
            <div className="max-h-32 space-y-1 overflow-y-auto">
              {state?.steps?.map((st, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
                  {st.status === "ok" ? (
                    <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                  ) : st.status === "error" ? (
                    <XCircle className="h-3 w-3 text-red-500" />
                  ) : (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  )}
                  <span className="font-mono">{st.step}</span>
                </div>
              ))}
            </div>
          </div>
        )}

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

          <Button onClick={handleRun} disabled={running || starting}>
            {running || starting ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="mr-2 h-3.5 w-3.5" />
            )}
            {running ? "Running…" : "Run Pipeline"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
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
