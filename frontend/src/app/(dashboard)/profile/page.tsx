"use client";

import { useEffect, useRef, useState } from "react";
import { Save, X, Loader2, RefreshCw, FileText, Star, Upload, Plus } from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { api, type ProfileSearchCriteria, type ProfileResume } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

function TagInput({
  label,
  tags,
  onAdd,
  onRemove,
  placeholder,
}: {
  label: string;
  tags: string[];
  onAdd: (tag: string) => void;
  onRemove: (tag: string) => void;
  placeholder?: string;
}) {
  const [input, setInput] = useState("");

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && input.trim()) {
      e.preventDefault();
      onAdd(input.trim());
      setInput("");
    }
  }

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-foreground">{label}</label>
      <div className="rounded-lg border p-3">
        <div className="mb-2 flex flex-wrap gap-2">
          {tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded-md bg-secondary px-2.5 py-1 text-xs font-medium text-secondary-foreground"
            >
              {tag}
              <button onClick={() => onRemove(tag)} className="ml-0.5 rounded-sm hover:bg-muted-foreground/20">
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          {tags.length === 0 && <span className="text-xs text-muted-foreground">None yet</span>}
        </div>
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || "Type and press Enter to add"}
          className="h-8 border-0 p-0 focus-visible:ring-0 focus-visible:ring-offset-0"
        />
      </div>
    </div>
  );
}

/**
 * Profile page (Phase 3.7): the signed-in user's own saved resume(s) and
 * search criteria -- distinct from /settings, which configures the global
 * pipeline (scraper keyword filters, LLM backend, etc). This page is
 * backed by the per-user `search_criteria`/`resumes` tables via
 * /api/profile/* (api/main.py), scoped to the authenticated user.
 */
export default function ProfilePage() {
  const { user } = useAuth();
  const [criteria, setCriteria] = useState<ProfileSearchCriteria | null>(null);
  const [resumes, setResumes] = useState<ProfileResume[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasCriteria, setHasCriteria] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [resumeList, criteriaResult] = await Promise.all([
        api.profile.getResumes(),
        api.profile.getSearchCriteria().catch((e: any) => {
          // No criteria saved yet (e.g. signed in without ever uploading a
          // resume through the anonymous hook) -- not an error, just an
          // empty profile to fill in.
          setHasCriteria(false);
          return {
            roles: [],
            tech_stack: [],
            seniority: null,
            locations: [],
            remote_pref: null,
            inferred_from_resume: false,
          } as ProfileSearchCriteria;
        }),
      ]);
      setResumes(resumeList);
      setCriteria(criteriaResult);
    } catch (e: any) {
      setError(e?.message || "Failed to load profile");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function handleUploadResumeFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await api.profile.uploadResume(file);
      toast.success("Resume uploaded & search criteria updated!");
      await load();
    } catch (err: any) {
      toast.error(err?.message || "Failed to upload resume");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function updateList(key: keyof ProfileSearchCriteria, updater: (list: string[]) => string[]) {
    setCriteria((c) => (c ? { ...c, [key]: updater((c[key] as string[]) || []) } : c));
  }

  async function handleSave() {
    if (!criteria) return;
    setSaving(true);
    try {
      const saved = await api.profile.updateSearchCriteria({
        roles: criteria.roles,
        tech_stack: criteria.tech_stack,
        seniority: criteria.seniority,
        locations: criteria.locations,
        remote_pref: criteria.remote_pref,
      });
      setCriteria(saved);
      setHasCriteria(true);
      toast.success("Profile saved");
    } catch (e: any) {
      toast.error(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <PageTransition>
      <Header
        title="Profile"
        description={user?.email ? `Signed in as ${user.email}` : "Your saved resume and search criteria"}
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={load} disabled={loading}>
              <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Reload
            </Button>
            <Button size="sm" onClick={handleSave} disabled={saving || loading || !criteria}>
              {saving ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <Save className="mr-2 h-3.5 w-3.5" />}
              Save Changes
            </Button>
          </div>
        }
      />

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error} — is the API running on port 8000?
        </div>
      )}

      {loading || !criteria ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Loading profile…
        </div>
      ) : (
        <div className="space-y-6 pb-16">
          {!hasCriteria && (
            <div className="rounded-xl border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
              You haven&apos;t uploaded a resume yet. Fill in your search criteria below, or upload a
              resume from the landing page to have it inferred automatically.
            </div>
          )}

          <Card>
            <CardContent className="space-y-6 p-6">
              <TagInput
                label="Target Roles"
                tags={criteria.roles}
                onAdd={(t) => updateList("roles", (l) => [...l, t])}
                onRemove={(t) => updateList("roles", (l) => l.filter((x) => x !== t))}
                placeholder="e.g. Backend Engineer, Full Stack Developer…"
              />
              <Separator />
              <TagInput
                label="Tech Stack"
                tags={criteria.tech_stack}
                onAdd={(t) => updateList("tech_stack", (l) => [...l, t])}
                onRemove={(t) => updateList("tech_stack", (l) => l.filter((x) => x !== t))}
                placeholder="e.g. Python, React, Postgres…"
              />
              <Separator />
              <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Seniority</label>
                  <Input
                    value={criteria.seniority ?? ""}
                    onChange={(e) => setCriteria((c) => (c ? { ...c, seniority: e.target.value || null } : c))}
                    placeholder="e.g. mid, senior"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Remote Preference</label>
                  <Input
                    value={criteria.remote_pref ?? ""}
                    onChange={(e) => setCriteria((c) => (c ? { ...c, remote_pref: e.target.value || null } : c))}
                    placeholder="e.g. remote, hybrid, onsite"
                  />
                </div>
              </div>
              <Separator />
              <TagInput
                label="Locations"
                tags={criteria.locations}
                onAdd={(t) => updateList("locations", (l) => [...l, t])}
                onRemove={(t) => updateList("locations", (l) => l.filter((x) => x !== t))}
                placeholder="e.g. Remote, San Francisco, Bengaluru…"
              />
            </CardContent>
          </Card>

          <div>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-foreground">Resume Versions</h2>
                <p className="text-xs text-muted-foreground">Upload or update your primary resume PDF/DOCX version</p>
              </div>
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleUploadResumeFile}
                accept=".pdf,.docx,.txt"
                className="hidden"
              />
              <Button
                variant="outline"
                size="sm"
                disabled={uploading}
                onClick={() => fileInputRef.current?.click()}
                className="border-accent1/30 text-accent1 hover:bg-accent1/10 font-medium"
              >
                {uploading ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Upload className="mr-1.5 h-3.5 w-3.5" />
                )}
                Upload New Resume
              </Button>
            </div>
            {resumes.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No resumes saved yet. Upload one from the landing page to get started.
              </p>
            ) : (
              <div className="space-y-2">
                {resumes.map((r) => (
                  <div
                    key={r.id}
                    className="flex items-center justify-between rounded-xl border bg-card px-4 py-3"
                  >
                    <div className="flex items-center gap-3">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          {(r.parsed_json as any)?.name || "Resume"}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Saved {new Date(r.created_at).toLocaleString()}
                        </p>
                      </div>
                    </div>
                    {r.is_primary && (
                      <span className="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-1 text-xs font-medium text-secondary-foreground">
                        <Star className="h-3 w-3" />
                        Primary
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </PageTransition>
  );
}
