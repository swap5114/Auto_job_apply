"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Paperclip, ArrowUp, Loader2, Sparkles, CheckCircle2, Flame } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth-context";
import { api, type MatchedJob } from "@/lib/api";

/**
 * Hero onboarding chat (v1 Task 9): the visitor attaches a resume and types
 * who they're targeting. On send, if they're not signed in we run Google
 * sign-in first (the gate), then match them against YC startups. Approving a
 * match saves it as an outreach lead and kicks the pipeline (Task 10).
 */
export function HeroChat() {
  const router = useRouter();
  const { user, signInWithGoogle } = useAuth();
  const fileRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [target, setTarget] = useState("");
  const [loading, setLoading] = useState(false);
  const [matches, setMatches] = useState<MatchedJob[] | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSend() {
    if (!file) {
      toast.error("Attach your resume first (PDF, DOCX, or TXT)");
      fileRef.current?.click();
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // The sign-in gate: unauthenticated sends run Google sign-in first.
      if (!user) {
        await signInWithGoogle();
      }
      const result = await api.chat.match(file, target);
      setMatches(result.matched_jobs);
      if (result.matched_jobs.length === 0) {
        toast("No YC matches yet for that — try a broader target or a fuller resume.");
      }
    } catch (e: any) {
      const msg = e?.message || "Something went wrong";
      // A cancelled/blocked Google popup throws -- don't nag about that.
      if (/popup|cancel|closed by the user|closed the popup/i.test(msg)) {
        setError("Sign-in was cancelled. Click send again to continue.");
      } else {
        setError(msg);
        toast.error(msg);
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleSave(job: MatchedJob) {
    setSavingId(job.id);
    try {
      const lead = await api.jobs.save(job.id);
      setMatches((prev) =>
        prev
          ? prev.map((j) => (j.id === job.id ? { ...j, already_saved_lead_id: lead.id } : j))
          : prev
      );
      toast.success(`Saved ${job.company_name}`);
    } catch (e: any) {
      toast.error(e?.message || "Couldn't save this startup");
    } finally {
      setSavingId(null);
    }
  }

  async function startPipeline() {
    const savedIds = (matches || [])
      .filter((j) => j.already_saved_lead_id)
      .map((j) => j.already_saved_lead_id as string);
    if (savedIds.length === 0) {
      toast.error("Save at least one startup first");
      return;
    }
    setStarting(true);
    try {
      await api.pipeline.runForLeads(savedIds);
      toast.success("Pipeline started — tailoring resumes and drafting outreach");
      router.push("/review");
    } catch (e: any) {
      toast.error(e?.message || "Couldn't start the pipeline");
      setStarting(false);
    }
  }

  // --- Results view -------------------------------------------------------
  if (matches) {
    const savedCount = matches.filter((m) => m.already_saved_lead_id).length;
    return (
      <div className="rounded-2xl border border-border/70 bg-card p-5 shadow-card">
        <div className="mb-4 flex items-center justify-between">
          <p className="flex items-center gap-2 text-sm font-medium text-foreground">
            <Sparkles className="h-4 w-4 text-accent1" />
            {matches.length} matching YC startups
          </p>
          <button
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setMatches(null)}
          >
            Start over
          </button>
        </div>

        <div className="max-h-[360px] space-y-3 overflow-y-auto pr-1">
          {matches.map((job) => {
            const saved = !!job.already_saved_lead_id;
            return (
              <div key={job.id} className="rounded-xl border border-border/60 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-foreground">{job.company_name}</p>
                    <p className="text-xs text-muted-foreground">{job.title}</p>
                  </div>
                  <span className="flex shrink-0 items-center gap-1 rounded-full bg-accent1/10 px-2 py-0.5 text-[11px] font-semibold text-accent1">
                    <Flame className="h-3 w-3" />
                    {job.match_score}
                  </span>
                </div>
                {job.matched_signals?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {job.matched_signals.slice(0, 6).map((s) => (
                      <Badge key={s} variant="outline" className="text-[10px] capitalize">
                        {s}
                      </Badge>
                    ))}
                  </div>
                )}
                <div className="mt-3 flex justify-end">
                  {saved ? (
                    <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600">
                      <CheckCircle2 className="h-3.5 w-3.5" /> Saved
                    </span>
                  ) : (
                    <Button size="sm" variant="outline" disabled={savingId === job.id} onClick={() => handleSave(job)}>
                      {savingId === job.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <Button className="mt-4 w-full" disabled={savedCount === 0 || starting} onClick={startPipeline}>
          {starting ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="mr-2 h-4 w-4" />
          )}
          Start outreach for {savedCount} saved {savedCount === 1 ? "startup" : "startups"}
        </Button>
      </div>
    );
  }

  // --- Input view ---------------------------------------------------------
  return (
    <div className="rounded-2xl border border-border/70 bg-card p-5 shadow-card">
      <p className="mb-3 text-sm font-medium text-foreground">
        Tell us who you&apos;re targeting
      </p>
      <div className="rounded-xl border border-input bg-background p-3">
        <textarea
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="e.g. Seed-stage AI infra startups using Python and Rust, backend or platform roles…"
          rows={3}
          className="w-full resize-none bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
        <div className="mt-2 flex items-center justify-between">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-input px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-accent"
          >
            <Paperclip className="h-3.5 w-3.5" />
            {file ? file.name : "Attach resume"}
          </button>
          <Button size="icon" className="h-8 w-8" disabled={loading} onClick={handleSend}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
          </Button>
        </div>
      </div>
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.docx,.txt"
        className="hidden"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      {error ? (
        <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      ) : (
        <p className="mt-3 text-xs text-muted-foreground">
          {user ? "Matched against YC startups hiring now." : "You'll sign in with Google to see your matches."}
        </p>
      )}
    </div>
  );
}
