"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Upload,
  FileText,
  Loader2,
  Sparkles,
  Building2,
  ArrowRight,
  AlertCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { api, type AnonResumeUploadResult } from "@/lib/api";
import { saveAnonSession } from "@/lib/anon-session";

const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".txt"];
const MAX_BYTES = 5 * 1024 * 1024;

/**
 * The landing page's real product demo -- replaces the old static
 * HeroPreview mockup with an actually-working resume-upload-to-matches
 * flow (Phase 6). This is the "wow in the first 30-60 seconds" moment for
 * an anonymous visitor: drop a resume, get real ranked matches from the
 * live catalog within a few seconds, no signup required to see them.
 *
 * On success, parsed_resume + inferred_criteria are stashed in
 * sessionStorage (anon-session.ts) so /signin can convert them into a
 * real account without re-uploading -- matched_jobs itself is NOT
 * persisted (it doesn't need to be: /api/jobs/matched recomputes it
 * against the just-saved criteria the moment the visitor lands on the
 * signed-in Matches page).
 */
export function ResumeUploadWidget() {
  const router = useRouter();
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnonResumeUploadResult | null>(null);

  async function handleFile(file: File) {
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      setError(`Unsupported file type. Use ${ALLOWED_EXTENSIONS.join(", ")}.`);
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("File too large (max 5MB).");
      return;
    }

    setError(null);
    setUploading(true);
    try {
      const res = await api.anon.uploadResume(file);
      saveAnonSession({
        parsed_resume: res.parsed_resume,
        inferred_criteria: res.inferred_criteria,
      });
      setResult(res);
    } catch (e: any) {
      setError(e?.message || "Couldn't process that resume. Try a different file.");
    } finally {
      setUploading(false);
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }

  if (result) {
    return <MatchedJobsPreview result={result} onSignIn={() => router.push("/signin")} />;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 24, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.7, delay: 0.2, ease: [0.21, 1.02, 0.73, 1] }}
      className="rounded-2xl border bg-card p-6 shadow-dropdown"
    >
      <div className="flex items-center gap-3 border-b pb-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
          <Sparkles className="h-4 w-4 text-primary-foreground" />
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">See your matches instantly</p>
          <p className="text-xs text-muted-foreground">No signup required</p>
        </div>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => !uploading && fileInput.current?.click()}
        className={`mt-5 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
          dragging
            ? "border-accent1 bg-accent1/5"
            : "border-border hover:border-accent1/40 hover:bg-muted/30"
        } ${uploading ? "cursor-wait opacity-70" : "cursor-pointer"}`}
      >
        <input
          ref={fileInput}
          type="file"
          accept={ALLOWED_EXTENSIONS.join(",")}
          className="hidden"
          disabled={uploading}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
        />
        {uploading ? (
          <>
            <Loader2 className="h-7 w-7 animate-spin text-accent1" />
            <p className="mt-1 text-sm font-medium text-foreground">Reading your resume…</p>
            <p className="text-xs text-muted-foreground">Matching against the live job catalog</p>
          </>
        ) : (
          <>
            <div className="flex h-11 w-11 items-center justify-center rounded-full bg-muted">
              <Upload className="h-5 w-5 text-muted-foreground" />
            </div>
            <p className="mt-1 text-sm font-medium text-foreground">
              Drop your resume, or click to browse
            </p>
            <p className="text-xs text-muted-foreground">PDF, DOCX, or TXT — up to 5MB</p>
          </>
        )}
      </div>

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-3 flex items-center gap-2 overflow-hidden rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700"
          >
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            {error}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function MatchedJobsPreview({
  result,
  onSignIn,
}: {
  result: AnonResumeUploadResult;
  onSignIn: () => void;
}) {
  const preview = result.matched_jobs.slice(0, 3);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.5, ease: [0.21, 1.02, 0.73, 1] }}
      className="rounded-2xl border bg-card p-5 shadow-dropdown"
    >
      <div className="flex items-center justify-between border-b pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
            <Sparkles className="h-4 w-4 text-primary-foreground" />
          </div>
          <div>
            <p className="text-sm font-semibold text-foreground">
              {result.parsed_resume.name ? `Hey ${result.parsed_resume.name.split(" ")[0]},` : "Nice —"} we found your matches
            </p>
            <p className="text-xs text-muted-foreground">
              {result.matched_jobs.length} role{result.matched_jobs.length === 1 ? "" : "s"} matched
            </p>
          </div>
        </div>
        {result.matched_jobs.length > 0 && (
          <Badge variant="review">{result.matched_jobs.length} new</Badge>
        )}
      </div>

      {preview.length === 0 ? (
        <div className="py-8 text-center">
          <p className="text-sm text-muted-foreground">
            No matches in the catalog yet for your background — sign in and we&apos;ll keep
            watching as new roles come in.
          </p>
        </div>
      ) : (
        <div className="space-y-2 pt-4">
          {preview.map((job, i) => (
            <motion.div
              key={job.id}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.15 + i * 0.1 }}
              className="flex items-center justify-between rounded-lg border border-border/60 bg-background px-3 py-2.5"
            >
              <div className="flex items-center gap-2.5">
                <div className="flex h-7 w-7 items-center justify-center rounded-md bg-muted">
                  <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                </div>
                <div>
                  <p className="text-xs font-medium text-foreground">{job.company_name}</p>
                  <p className="text-[11px] text-muted-foreground">{job.title}</p>
                </div>
              </div>
              {job.match_score > 0 && (
                <Badge variant="outline" className="text-[10px]">
                  {job.match_score} match{job.match_score === 1 ? "" : "es"}
                </Badge>
              )}
            </motion.div>
          ))}
        </div>
      )}

      <button
        onClick={onSignIn}
        className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-[10px] bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground shadow-button-brand transition-all hover:shadow-button-brand-hover"
      >
        Sign in to save & apply
        <ArrowRight className="h-3.5 w-3.5" />
      </button>
      <p className="mt-2 text-center text-[11px] text-muted-foreground">
        Your resume and matches carry straight over — no re-upload.
      </p>
    </motion.div>
  );
}
