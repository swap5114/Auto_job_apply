"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Send,
  Loader2,
  Sparkles,
  FileEdit,
  RotateCcw,
  Upload,
  Zap,
  Download,
  Save,
  Replace as ReplaceIcon,
  LayoutList,
  Eye,
  EyeOff,
  GripVertical,
  Plus,
  ChevronDown,
  ChevronRight,
  Briefcase,
  CheckCircle2,
  Target,
  Wand2,
} from "lucide-react";
import { toast } from "sonner";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  api,
  type BaseResume,
  type ProfileResume,
  type ResumeTemplate,
  type ResumeDiff,
} from "@/lib/api";

type ChatMsg =
  | { kind: "user"; jd: string; company: string; role: string }
  | { kind: "result"; coverage: number; belowFloor: boolean; model: string; jdTruncated: boolean; maxJdChars: number; changedBullets: number }
  | { kind: "error"; text: string };

// The canonical, ordered set of resume sections.
const SECTION_DEFS: { id: SectionId; label: string }[] = [
  { id: "summary", label: "Summary" },
  { id: "education", label: "Education" },
  { id: "skills", label: "Skills" },
  { id: "experience", label: "Work Experience" },
  { id: "projects", label: "Projects" },
  { id: "certifications", label: "Certifications" },
];
type SectionId = "summary" | "education" | "skills" | "experience" | "projects" | "certifications";

export default function ResumePage() {
  const [base, setBase] = useState<BaseResume | null>(null);
  const [resumes, setResumes] = useState<ProfileResume[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [diff, setDiff] = useState<ResumeDiff | null>(null);
  const [coverage, setCoverage] = useState<number | null>(null);
  const [belowFloor, setBelowFloor] = useState(false);
  const [modelUsed, setModelUsed] = useState<string | null>(null);

  const [template, setTemplate] = useState<ResumeTemplate>("jake");
  const [sectionOrder, setSectionOrder] = useState<SectionId[]>(SECTION_DEFS.map((s) => s.id));
  const [hidden, setHidden] = useState<Set<SectionId>>(new Set());

  const [loading, setLoading] = useState(true);
  const [rephrasing, setRephrasing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");

  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [b, list] = await Promise.all([
        api.resume.base(),
        api.profile.getResumes().catch(() => [] as ProfileResume[]),
      ]);
      setBase(b);
      setResumes(list);
      const primary = list.find((r) => r.is_primary) || list[0];
      setSelectedId(primary?.id ?? null);
    } catch (e: any) {
      toast.error(e?.message || "Failed to load your resume");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, rephrasing]);

  // Which resume JSON is the "base" for display: the selected version's, else
  // the primary base resume.
  const selectedResume = useMemo(() => {
    const r = resumes.find((x) => x.id === selectedId);
    return (r?.parsed_json as ResumeShape | undefined) || (base?.parsed_json as ResumeShape | null) || null;
  }, [resumes, selectedId, base]);

  // The live-shown resume: preview (tailored) if present, else selected base.
  const shownRaw = (preview as ResumeShape | null) || selectedResume;
  const activeDiff = preview ? diff : null;

  // Apply the user's local edits (bullet reordering) to the shown resume.
  const [bulletOrder, setBulletOrder] = useState<BulletOrder>({ experience: {}, projects: {} });
  const shown = useMemo(
    () => (shownRaw ? applyBulletOrder(shownRaw, bulletOrder) : null),
    [shownRaw, bulletOrder]
  );

  const jdLen = input.trim().length;
  const jdMax = api.RESUME_MAX_JD_CHARS;
  const jdOver = jdLen > jdMax;

  async function handleSend() {
    const jd = input.trim();
    if (!jd || rephrasing) return;
    if (!base?.has_resume) {
      toast.error("Upload a base resume first.");
      return;
    }
    setMessages((m) => [...m, { kind: "user", jd, company: company.trim(), role: role.trim() }]);
    setInput("");
    setRephrasing(true);
    try {
      const currentJson = (preview as Record<string, unknown> | null) || (shown as Record<string, unknown> | null) || undefined;
      const res = await api.resume.rephrase({
        jd_text: jd,
        company: company.trim() || undefined,
        role: role.trim() || undefined,
        template,
        current_tailored_json: currentJson,
      });
      setPreview(res.tailored_json);
      setDiff(res.diff);
      setCoverage(res.keyword_coverage);
      setBelowFloor(res.ats_below_floor);
      setModelUsed(res.model_used);
      setBulletOrder({ experience: {}, projects: {} }); // reset edits to the new tailored base
      const changedBullets = countChangedBullets(res.diff);
      setMessages((m) => [
        ...m,
        {
          kind: "result",
          coverage: res.keyword_coverage,
          belowFloor: res.ats_below_floor,
          model: res.model_used,
          jdTruncated: res.jd_truncated,
          maxJdChars: res.max_jd_chars,
          changedBullets,
        },
      ]);
    } catch (e: any) {
      setMessages((m) => [...m, { kind: "error", text: e?.message || "Couldn't rephrase. Try again." }]);
      toast.error(e?.message || "Rephrase failed");
    } finally {
      setRephrasing(false);
    }
  }

  function resetPreview() {
    setPreview(null);
    setDiff(null);
    setCoverage(null);
    setBelowFloor(false);
    setModelUsed(null);
    setMessages([]);
    setBulletOrder({ experience: {}, projects: {} });
  }

  async function handleReplace(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const t = toast.loading("Uploading & parsing resume…");
    try {
      await api.profile.uploadResume(file);
      toast.success("Resume replaced.", { id: t });
      resetPreview();
      await load();
    } catch (err: any) {
      toast.error(err?.message || "Upload failed", { id: t });
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDownload() {
    if (!shown) return;
    setDownloading(true);
    try {
      const url = await api.resume.downloadPdfBlobUrl({
        resume_json: buildOrderedResume(shown, sectionOrder, hidden),
        template,
        filename: (shown.name as string) || "resume",
      });
      const a = document.createElement("a");
      a.href = url;
      a.download = `${((shown.name as string) || "resume").replace(/\s+/g, "_")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (e: any) {
      toast.error(e?.message || "Download failed");
    } finally {
      setDownloading(false);
    }
  }

  async function handleSave() {
    if (!shown) return;
    setSaving(true);
    try {
      const suggested =
        (company.trim() || (preview ? "Tailored" : "Edited")) +
        (role.trim() ? ` · ${role.trim()}` : "");
      const name = window.prompt("Name this resume version", suggested);
      if (name === null) {
        setSaving(false);
        return; // user cancelled
      }
      const saved = await api.profile.saveResume({
        parsed_json: buildOrderedResume(shown, sectionOrder, hidden),
        name: name.trim() || suggested,
      });
      toast.success("Resume version saved.");
      // Refresh the dropdown list and select the newly saved version.
      const list = await api.profile.getResumes().catch(() => resumes);
      setResumes(list);
      setSelectedId(saved.id);
      resetPreview();
    } catch (e: any) {
      toast.error(e?.message || "Couldn't save this version");
    } finally {
      setSaving(false);
    }
  }

  const modelLabel = modelUsed === "vertex_claude" ? "Claude" : modelUsed ? "Gemini" : null;

  const visibleOrder = sectionOrder.filter((s) => !hidden.has(s));

  return (
    <PageTransition>
      {/* Full-height shell — the page itself doesn't scroll; each pane manages
          its own overflow so the resume sits on the page like the reference. */}
      <div className="flex h-[calc(100vh-4rem)] flex-col gap-3">
        {loading ? (
          <div className="flex flex-1 items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            Loading your resume…
          </div>
        ) : !base?.has_resume ? (
          <NoBaseResume />
        ) : (
          <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(300px,360px)_1fr]">
            {/* Left — JD tailoring assistant */}
            <div className="relative flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border/70 bg-card shadow-card">
              {/* Header */}
              <div className="relative overflow-hidden border-b border-border/60 px-4 py-3.5">
                <div className="pointer-events-none absolute -right-8 -top-10 h-28 w-28 rounded-full accent-gradient opacity-[0.10] blur-2xl" />
                <div className="relative flex items-center gap-2.5">
                  <span className="flex h-8 w-8 items-center justify-center rounded-xl accent-gradient text-white shadow-sm">
                    <Sparkles className="h-4 w-4" />
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold leading-tight text-foreground">Tailoring assistant</h3>
                    <p className="text-[11px] text-muted-foreground">Paste a JD — your resume rewrites to match, honestly.</p>
                  </div>
                </div>
              </div>

              {/* Transcript */}
              <div className="flex-1 space-y-3 overflow-y-auto p-4">
                {messages.length === 0 && !rephrasing && (
                  <div className="flex h-full flex-col items-center justify-center px-4 text-center">
                    <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-accent1/10 text-accent1">
                      <FileEdit className="h-5 w-5" />
                    </span>
                    <p className="mt-3 text-sm font-medium text-foreground">Tailor to any role</p>
                    <p className="mt-1 max-w-[260px] text-xs leading-relaxed text-muted-foreground">
                      Drop a job description below. I&apos;ll rewrite your bullets and skills to
                      match its language — using only what&apos;s truly on your resume — and
                      highlight every change on the right.
                    </p>
                  </div>
                )}

                {messages.map((m, i) =>
                  m.kind === "user" ? (
                    <JdCard key={i} jd={m.jd} company={m.company} role={m.role} />
                  ) : m.kind === "result" ? (
                    <ResultCard key={i} msg={m} />
                  ) : (
                    <div key={i} className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                      {m.text}
                    </div>
                  )
                )}

                {rephrasing && (
                  <div className="flex items-center gap-2.5 rounded-xl border border-border/60 bg-muted/40 px-3 py-2.5">
                    <span className="relative flex h-6 w-6 items-center justify-center">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent1/30" />
                      <Loader2 className="relative h-3.5 w-3.5 animate-spin text-accent1" />
                    </span>
                    <span className="text-xs font-medium text-foreground">Tailoring your resume…</span>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              {/* Composer */}
              <div className="border-t border-border/60 bg-muted/20 p-3">
                <div className="mb-2 grid grid-cols-2 gap-2">
                  <input
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    placeholder="Company (optional)"
                    className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-accent1"
                  />
                  <input
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                    placeholder="Role (optional)"
                    className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-accent1"
                  />
                </div>
                <div
                  className={cn(
                    "rounded-xl border bg-card p-2 shadow-sm transition-shadow focus-within:ring-1",
                    jdOver ? "border-amber-400 focus-within:ring-amber-400" : "border-border focus-within:ring-accent1"
                  )}
                >
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault();
                        handleSend();
                      }
                    }}
                    rows={3}
                    placeholder="Paste the full job description here…"
                    className="max-h-40 w-full resize-none bg-transparent px-1.5 py-1 text-xs leading-relaxed text-foreground placeholder:text-muted-foreground focus:outline-none"
                  />
                  <div className="mt-1 flex items-center justify-between gap-2 px-1">
                    <span className={cn("text-[10px] tabular-nums", jdOver ? "text-amber-600" : "text-muted-foreground")}>
                      {jdLen.toLocaleString()}/{jdMax.toLocaleString()}
                      {jdOver && " — clipped"}
                    </span>
                    <Button size="sm" className="h-7 px-3" onClick={handleSend} disabled={rephrasing || !input.trim()}>
                      {rephrasing ? (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Send className="mr-1.5 h-3.5 w-3.5" />
                      )}
                      Tailor
                    </Button>
                  </div>
                </div>
                <p className="mt-1.5 px-1 text-[10px] text-muted-foreground">
                  <kbd className="rounded border border-border bg-muted px-1 py-0.5 text-[9px]">⌘/Ctrl</kbd>
                  {" + "}
                  <kbd className="rounded border border-border bg-muted px-1 py-0.5 text-[9px]">Enter</kbd>
                  {" to tailor · nothing is invented — only your real experience is used."}
                </p>
              </div>
            </div>

            {/* Right — resume document with full toolbar */}
            <div className="flex min-h-0 flex-col rounded-2xl border border-border/70 bg-card shadow-card">
              {/* Toolbar row 1: selector + Replace/Download */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-4 py-2.5">
                <ResumeSelector
                  resumes={resumes}
                  selectedId={selectedId}
                  onSelect={(id) => {
                    setSelectedId(id);
                    resetPreview();
                  }}
                />
                <div className="flex items-center gap-2">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.docx,.txt"
                    onChange={handleReplace}
                    className="hidden"
                  />
                  <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
                    <ReplaceIcon className="mr-2 h-3.5 w-3.5" />
                    Replace
                  </Button>
                  <Button variant="outline" size="sm" onClick={handleSave} disabled={saving || !shown}>
                    {saving ? (
                      <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Save className="mr-2 h-3.5 w-3.5" />
                    )}
                    Save
                  </Button>
                  <Button size="sm" onClick={handleDownload} disabled={downloading || !shown}>
                    {downloading ? (
                      <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Download className="mr-2 h-3.5 w-3.5" />
                    )}
                    Download
                  </Button>
                </div>
              </div>

              {/* Toolbar row 2: template, sections, reset, badges */}
              <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-4 py-2">
                <span className="text-[11px] font-medium text-muted-foreground">Template</span>
                <TemplateSwitcher value={template} onChange={setTemplate} />

                <SectionsMenu
                  order={sectionOrder}
                  hidden={hidden}
                  onReorder={setSectionOrder}
                  onToggleHide={(id) =>
                    setHidden((prev) => {
                      const next = new Set(prev);
                      next.has(id) ? next.delete(id) : next.add(id);
                      return next;
                    })
                  }
                  onAddCustom={() => toast("Custom sections are coming soon.")}
                />

                <div className="ml-auto flex items-center gap-2">
                  {preview && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-accent1/10 px-2 py-0.5 text-[10px] font-medium text-accent1">
                      <span className="h-2 w-2 rounded-sm bg-amber-300/70 ring-1 ring-amber-400/60" />
                      changed
                    </span>
                  )}
                  {modelLabel && (
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium",
                        modelUsed === "vertex_claude" ? "bg-violet-50 text-violet-700" : "bg-muted text-muted-foreground"
                      )}
                    >
                      {modelUsed === "vertex_claude" && <Zap className="h-3 w-3" />}
                      {modelLabel}
                    </span>
                  )}
                  {preview && (
                    <Button variant="ghost" size="sm" onClick={resetPreview}>
                      <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                      Reset
                    </Button>
                  )}
                </div>
              </div>

              {/* Document */}
              <div className="min-h-0 flex-1 overflow-y-auto bg-muted/30 p-6">
                {shown ? (
                  <div className="mx-auto max-w-[780px] rounded-lg bg-white p-9 shadow-sm ring-1 ring-border">
                    <ResumeDocument
                      resume={shown}
                      diff={activeDiff}
                      template={template}
                      order={visibleOrder}
                      bulletOrder={bulletOrder}
                      onReorderBullets={(section, entryIdx, next) =>
                        setBulletOrder((prev) => ({
                          ...prev,
                          [section]: { ...prev[section], [entryIdx]: next },
                        }))
                      }
                    />
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No resume to show.</p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </PageTransition>
  );
}

// ---------------------------------------------------------------------------
// Resume selector
// ---------------------------------------------------------------------------

function ResumeSelector({
  resumes,
  selectedId,
  onSelect,
}: {
  resumes: ProfileResume[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const current = resumes.find((r) => r.id === selectedId);
  const getLabel = (r: ProfileResume | undefined) => {
    if (!r) return "Base Resume";
    if (r.is_primary) return "Primary Base Resume";
    return r.file_ref || (r.parsed_json as any)?.name || "Saved Version";
  };
  const label = getLabel(current);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted/50"
      >
        {label}
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
      </button>
      {open && resumes.length > 0 && (
        <div className="absolute left-0 top-full z-20 mt-1 w-64 overflow-hidden rounded-lg border border-border bg-card shadow-dropdown">
          {resumes.map((r) => {
            const itemLabel = getLabel(r);
            return (
              <button
                key={r.id}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onSelect(r.id);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-muted",
                  r.id === selectedId ? "font-semibold text-foreground bg-muted/40" : "text-muted-foreground"
                )}
              >
                <span className="truncate">{itemLabel}</span>
                {r.is_primary && <span className="ml-2 rounded bg-accent1/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent1">primary</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Template switcher
// ---------------------------------------------------------------------------

function TemplateSwitcher({ value, onChange }: { value: ResumeTemplate; onChange: (t: ResumeTemplate) => void }) {
  const opts: { id: ResumeTemplate; label: string }[] = [
    { id: "standard", label: "Standard" },
    { id: "jake", label: "Jake" },
  ];
  return (
    <div className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5">
      {opts.map((o) => (
        <button
          key={o.id}
          onClick={() => onChange(o.id)}
          className={cn(
            "rounded-md px-3 py-1 text-xs font-medium transition-colors",
            value === o.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sections popover — reorder (drag) + hide (eye) + add custom
// ---------------------------------------------------------------------------

function SectionsMenu({
  order,
  hidden,
  onReorder,
  onToggleHide,
  onAddCustom,
}: {
  order: SectionId[];
  hidden: Set<SectionId>;
  onReorder: (next: SectionId[]) => void;
  onToggleHide: (id: SectionId) => void;
  onAddCustom: () => void;
}) {
  const [open, setOpen] = useState(false);
  const dragIdx = useRef<number | null>(null);

  const labelOf = (id: SectionId) => SECTION_DEFS.find((s) => s.id === id)?.label || id;

  function handleDrop(target: number) {
    const from = dragIdx.current;
    dragIdx.current = null;
    if (from == null || from === target) return;
    const next = [...order];
    const [moved] = next.splice(from, 1);
    next.splice(target, 0, moved);
    onReorder(next);
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted/50"
      >
        <LayoutList className="h-3.5 w-3.5" />
        Sections
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1 w-72 rounded-xl border border-border bg-card p-2 shadow-dropdown">
            <p className="px-2 pb-1.5 pt-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Drag to reorder · click the eye to hide
            </p>
            <div className="space-y-0.5">
              {order.map((id, i) => {
                const isHidden = hidden.has(id);
                return (
                  <div
                    key={id}
                    draggable
                    onDragStart={() => (dragIdx.current = i)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => handleDrop(i)}
                    className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-muted/60"
                  >
                    <span className="flex h-5 w-5 items-center justify-center text-[10px] font-semibold text-muted-foreground">
                      {i + 1}
                    </span>
                    <GripVertical className="h-3.5 w-3.5 cursor-grab text-muted-foreground" />
                    <span className={cn("flex-1 text-sm", isHidden ? "text-muted-foreground line-through" : "text-foreground")}>
                      {labelOf(id)}
                    </span>
                    <button
                      onClick={() => onToggleHide(id)}
                      className="text-muted-foreground hover:text-foreground"
                      title={isHidden ? "Show section" : "Hide section"}
                    >
                      {isHidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                );
              })}
            </div>
            <button
              onClick={onAddCustom}
              className="mt-1.5 flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-accent1 hover:bg-accent1/5"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Custom Section
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Resume document (renders sections in the given order + DnD bullets)
// ---------------------------------------------------------------------------

type ResumeShape = {
  name?: string;
  contact?: Record<string, string>;
  summary?: string;
  education?: { institution?: string; degree?: string; start_date?: string; end_date?: string; details?: string }[];
  experience?: { company?: string; title?: string; start_date?: string; end_date?: string; bullets?: string[] }[];
  projects?: { name?: string; date?: string; tech_stack?: string[]; link?: string; bullets?: string[] }[];
  skills?: Record<string, string[]>;
  certifications?: string[];
};

type BulletOrder = {
  experience: Record<number, number[]>;
  projects: Record<number, number[]>;
};

/** Reorder bullets in a resume per the user's local drag edits. */
function applyBulletOrder(resume: ResumeShape, order: BulletOrder): ResumeShape {
  const reorder = (bullets: string[] | undefined, perm: number[] | undefined) => {
    if (!bullets) return bullets;
    if (!perm) return bullets;
    const valid = perm.filter((i) => i >= 0 && i < bullets.length);
    if (valid.length !== bullets.length) return bullets;
    return valid.map((i) => bullets[i]);
  };
  return {
    ...resume,
    experience: (resume.experience || []).map((e, i) => ({ ...e, bullets: reorder(e.bullets, order.experience[i]) })),
    projects: (resume.projects || []).map((p, i) => ({ ...p, bullets: reorder(p.bullets, order.projects[i]) })),
  };
}

/** Ensure a link has a scheme so the browser treats it as absolute — a bare
 *  domain like "foo.vercel.app" would otherwise resolve relative to the
 *  current origin (localhost). mailto:/tel: and http(s) links pass through. */
function normalizeUrl(url: string): string {
  const u = (url || "").trim();
  if (!u) return u;
  if (/^(https?:|mailto:|tel:)/i.test(u)) return u;
  return `https://${u.replace(/^\/+/, "")}`;
}

/** A short, human-readable form of a URL for display (drops scheme + trailing
 *  slash) — the visible clickable text, while the href stays the full URL. */
function prettyUrl(url: string): string {
  return (url || "").trim().replace(/^https?:\/\//i, "").replace(/\/+$/, "");
}

/** Build a resume object with sections applied in `order`, dropping hidden ones. */
function buildOrderedResume(resume: ResumeShape, order: SectionId[], hidden: Set<SectionId>): Record<string, unknown> {
  const out: Record<string, unknown> = { name: resume.name, contact: resume.contact };
  for (const id of order) {
    if (hidden.has(id)) continue;
    if (id === "summary") out.summary = resume.summary;
    else out[id] = (resume as any)[id];
  }
  return out;
}

function contactParts(contact: Record<string, string> = {}) {
  return [
    contact.location, contact.phone, contact.email,
    contact.linkedin && "LinkedIn", contact.github && "GitHub", contact.portfolio && "Portfolio",
  ].filter(Boolean) as string[];
}

function ResumeDocument({
  resume,
  diff,
  template,
  order,
  bulletOrder,
  onReorderBullets,
}: {
  resume: ResumeShape;
  diff: ResumeDiff | null;
  template: ResumeTemplate;
  order: SectionId[];
  bulletOrder: BulletOrder;
  onReorderBullets: (section: "experience" | "projects", entryIdx: number, next: number[]) => void;
}) {
  const jake = template === "jake";
  const parts = contactParts(resume.contact);

  const H = ({ children }: { children: React.ReactNode }) =>
    jake ? (
      <h2 className="mt-3 border-b border-black pb-0.5 text-[13px] font-bold uppercase tracking-wide">{children}</h2>
    ) : (
      <h2 className="mt-4 border-b border-slate-600 pb-1 text-[12px] font-bold uppercase tracking-wide text-slate-900">
        {children}
      </h2>
    );

  function renderSection(id: SectionId) {
    switch (id) {
      case "summary":
        return resume.summary ? (
          <div key={id}>
            <H>Summary</H>
            <p className={cn("mt-1", diff?.summary && "rounded-sm bg-amber-100/70 px-1")}>{resume.summary}</p>
          </div>
        ) : null;
      case "experience":
        return (resume.experience?.length ?? 0) > 0 ? (
          <div key={id}>
            <H>{jake ? "Experience" : "Experience"}</H>
            <div className="mt-1">
              {resume.experience!.map((exp, i) => (
                <div key={i} className="mb-2">
                  <div className="flex items-baseline justify-between">
                    <span className={jake ? "font-bold" : "font-bold"}>
                      {jake
                        ? exp.title
                        : [exp.company, exp.title].filter(Boolean).join(" | ")}
                    </span>
                    <span className="text-[11px] text-slate-500">{[exp.start_date, exp.end_date].filter(Boolean).join(" – ")}</span>
                  </div>
                  {jake && <p className="italic">{exp.company}</p>}
                  <BulletList
                    bullets={exp.bullets || []}
                    changed={diff?.experience?.[i]}
                    jake={jake}
                    onReorder={(perm) => onReorderBullets("experience", i, perm)}
                  />
                </div>
              ))}
            </div>
          </div>
        ) : null;
      case "projects":
        return (resume.projects?.length ?? 0) > 0 ? (
          <div key={id}>
            <H>Projects</H>
            <div className="mt-1">
              {resume.projects!.map((p, i) => (
                <div key={i} className="mb-2">
                  <div className="flex items-baseline justify-between">
                    <span className={jake ? "font-bold" : "font-semibold"}>
                      {p.name}
                      {p.link && (
                        <>
                          {" "}
                          <a
                            href={normalizeUrl(p.link)}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={normalizeUrl(p.link)}
                            className="break-all text-[11px] font-normal text-blue-600 underline"
                          >
                            {prettyUrl(p.link)}
                          </a>
                        </>
                      )}
                    </span>
                    <span className="text-[11px] text-slate-500">{p.date}</span>
                  </div>
                  {(p.tech_stack?.length ?? 0) > 0 && (
                    <p className="text-[11px] italic text-slate-500">{p.tech_stack!.join(jake ? " · " : ", ")}</p>
                  )}
                  <BulletList
                    bullets={p.bullets || []}
                    changed={diff?.projects?.[i]}
                    jake={jake}
                    onReorder={(perm) => onReorderBullets("projects", i, perm)}
                  />
                </div>
              ))}
            </div>
          </div>
        ) : null;
      case "skills":
        return resume.skills && Object.keys(resume.skills).length > 0 ? (
          <div key={id}>
            <H>{jake ? "Technical Skills" : "Skills"}</H>
            <div className="mt-1">
              {Object.entries(resume.skills).map(([cat, items]) => (
                <p key={cat} className="mb-0.5 leading-relaxed">
                  <span className={jake ? "font-bold" : "font-semibold"}>{cat}:</span>{" "}
                  {(items || []).map((it, k) => (
                    <span key={k} className={cn(diff?.skills?.[cat]?.[k] && "rounded-sm bg-amber-100/70 px-0.5")}>
                      {it}{k < (items || []).length - 1 ? ", " : ""}
                    </span>
                  ))}
                </p>
              ))}
            </div>
          </div>
        ) : null;
      case "education":
        return (resume.education?.length ?? 0) > 0 ? (
          <div key={id}>
            <H>Education</H>
            <div className="mt-1">
              {resume.education!.map((e, i) => (
                <div key={i} className="flex items-baseline justify-between">
                  <span>
                    <span className={jake ? "font-bold" : "font-semibold"}>{e.institution}</span>
                    {e.degree ? ` — ${e.degree}` : ""}
                  </span>
                  <span className="text-[11px] text-slate-500">{[e.start_date, e.end_date].filter(Boolean).join(" – ")}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null;
      case "certifications":
        return (resume.certifications?.length ?? 0) > 0 ? (
          <div key={id}>
            <H>Certifications</H>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {resume.certifications!.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          </div>
        ) : null;
    }
  }

  return (
    <div className={cn(jake ? "font-serif text-[13px] leading-snug text-black" : "text-[13px] leading-relaxed text-slate-900")}>
      <h1 className="text-center text-2xl font-bold tracking-tight">{resume.name}</h1>
      {parts.length > 0 && (
        <p className="mt-0.5 text-center text-[11px] text-slate-500">
          {parts.join(jake ? "  |  " : "  |  ")}
        </p>
      )}
      {order.map((id) => renderSection(id))}
    </div>
  );
}

/** A draggable bullet list — reorder points within one entry. */
function BulletList({
  bullets,
  changed,
  jake,
  onReorder,
}: {
  bullets: string[];
  changed?: boolean[];
  jake: boolean;
  onReorder: (perm: number[]) => void;
}) {
  const dragIdx = useRef<number | null>(null);
  const [overIdx, setOverIdx] = useState<number | null>(null);

  function handleDrop(target: number) {
    const from = dragIdx.current;
    dragIdx.current = null;
    setOverIdx(null);
    if (from == null || from === target) return;
    const perm = bullets.map((_, i) => i);
    const [moved] = perm.splice(from, 1);
    perm.splice(target, 0, moved);
    onReorder(perm);
  }

  return (
    <ul className={cn("mt-0.5 list-disc space-y-0.5 pl-5", jake && "text-justify")}>
      {bullets.map((b, j) => (
        <li
          key={j}
          draggable
          onDragStart={() => (dragIdx.current = j)}
          onDragOver={(e) => {
            e.preventDefault();
            setOverIdx(j);
          }}
          onDrop={() => handleDrop(j)}
          className={cn(
            "group relative cursor-grab list-item",
            changed?.[j] && "rounded-sm bg-amber-100/70 px-1 -mx-1 ring-1 ring-amber-200",
            overIdx === j && "outline-dashed outline-1 outline-accent1"
          )}
          title="Drag to reorder"
        >
          {b}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Chat cards: the JD the user pasted, and the tailoring result
// ---------------------------------------------------------------------------

/** Count how many bullets the tailoring changed, from the diff map. */
function countChangedBullets(diff: ResumeDiff | null): number {
  if (!diff) return 0;
  let n = 0;
  for (const section of [diff.experience, diff.projects]) {
    for (const entry of section || []) {
      for (const changed of entry || []) if (changed) n++;
    }
  }
  return n;
}

/** The job description the user submitted — shown in full (expandable), so
 *  they can see exactly what the resume was tailored against. */
function JdCard({ jd, company, role }: { jd: string; company: string; role: string }) {
  const [open, setOpen] = useState(false);
  const long = jd.length > 320;
  const shown = open || !long ? jd : jd.slice(0, 320).trimEnd() + "…";
  const words = jd.trim().split(/\s+/).filter(Boolean).length;

  return (
    <div className="ml-auto max-w-[92%] overflow-hidden rounded-2xl rounded-br-md border border-border bg-primary text-primary-foreground shadow-sm">
      <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
        <Briefcase className="h-3.5 w-3.5 opacity-80" />
        <span className="truncate text-xs font-semibold">
          {[role || null, company || null].filter(Boolean).join(" · ") || "Job description"}
        </span>
        <span className="ml-auto shrink-0 text-[10px] tabular-nums text-primary-foreground/60">
          {words} words
        </span>
      </div>
      <p className="whitespace-pre-wrap px-3 py-2.5 text-[11px] leading-relaxed text-primary-foreground/90">
        {shown}
      </p>
      {long && (
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-1 border-t border-white/10 px-3 py-1.5 text-[10px] font-medium text-primary-foreground/70 hover:text-primary-foreground"
        >
          {open ? "Show less" : "Show full JD"}
          <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
        </button>
      )}
    </div>
  );
}

/** The tailoring result — ATS score, model, and what changed. */
function ResultCard({
  msg,
}: {
  msg: { coverage: number; belowFloor: boolean; model: string; jdTruncated: boolean; maxJdChars: number; changedBullets: number };
}) {
  const modelLabel = msg.model === "vertex_claude" ? "Claude" : msg.model?.includes("pro") ? "Gemini Pro" : "Gemini";
  return (
    <div className="max-w-[92%] overflow-hidden rounded-2xl rounded-bl-md border border-border bg-card shadow-sm">
      <div className="flex items-center gap-2 border-b border-border/60 bg-muted/30 px-3 py-2">
        <span className="flex h-5 w-5 items-center justify-center rounded-md accent-gradient text-white">
          <Wand2 className="h-3 w-3" />
        </span>
        <span className="text-xs font-semibold text-foreground">Resume tailored</span>
        <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
          {msg.model === "vertex_claude" && <Zap className="h-2.5 w-2.5" />}
          {modelLabel}
        </span>
      </div>

      <div className="p-3">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-2.5 py-2">
          <CheckCircle2 className="h-4 w-4 text-accent1" />
          <div className="leading-tight">
            <p className="text-sm font-bold tabular-nums text-foreground">{msg.changedBullets}</p>
            <p className="text-[9px] uppercase tracking-wide text-muted-foreground">lines reworded to match the JD</p>
          </div>
        </div>
      </div>

      <p className="px-3 pb-3 text-[11px] leading-relaxed text-muted-foreground">
        {msg.belowFloor
          ? "Tailored honestly — I won't add skills you don't have. Changed lines are highlighted on the right."
          : "Your resume now mirrors this role's language. Every changed line is highlighted on the right — review, then save or download."}
        {msg.jdTruncated && ` (JD was long; used the first ${msg.maxJdChars.toLocaleString()} characters.)`}
      </p>
    </div>
  );
}

function NoBaseResume() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full accent-gradient">
        <FileEdit className="h-7 w-7 text-white" />
      </div>
      <h3 className="mt-4 font-display text-xl text-foreground">No base resume yet</h3>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">
        Upload your resume on your profile and it becomes the base we tailor against every job.
      </p>
      <Button asChild className="mt-5">
        <Link href="/profile">
          <Upload className="mr-1.5 h-3.5 w-3.5" />
          Upload resume
        </Link>
      </Button>
    </div>
  );
}
