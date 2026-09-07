"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  Hammer,
  Loader2,
  RefreshCw,
  ExternalLink,
  Plus,
  Send,
  Sparkles,
  Layers,
  Code2,
  CheckCircle2,
  XCircle,
  Clock,
  Terminal,
} from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";

interface DemoBuildItem {
  id?: string;
  build_id: string;
  title: string;
  company_name?: string;
  project_type?: "fullstack" | "frontend_only" | "backend_only";
  stage: string;
  deploy_stage?: string | null;
  repo_url?: string | null;
  frontend_url?: string | null;
  backend_url?: string | null;
  error?: string | null;
  deploy_error?: string | null;
  refinements?: Array<{ prompt: string; timestamp: string; stage: string }>;
  created_at?: string;
}

export default function BuildsPage() {
  const [builds, setBuilds] = useState<DemoBuildItem[]>([]);
  const [activeBuild, setActiveBuild] = useState<DemoBuildItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [quota, setQuota] = useState<{ used: number; limit: number; remaining: number } | null>(null);

  // New Demo Form state
  const [showNewForm, setShowNewForm] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [company, setCompany] = useState("");
  const [projectType, setProjectType] = useState<"fullstack" | "frontend_only" | "backend_only">("fullstack");
  const [building, setBuilding] = useState(false);

  // Refinement prompt state
  const [refinePrompt, setRefinePrompt] = useState("");
  const [refining, setRefining] = useState(false);

  async function loadData() {
    try {
      const [listData, quotaData] = await Promise.all([
        api.demos.list().catch(() => []),
        api.demos.quota().catch(() => ({ date: "", used: 0, limit: 5, remaining: 5 })),
      ]);
      setBuilds(listData as any[]);
      setQuota(quotaData);
      setError(null);

      // If active build is running, update activeBuild reference
      if (activeBuild) {
        const updated = (listData as any[]).find((b) => b.build_id === activeBuild.build_id);
        if (updated) setActiveBuild(updated);
      } else if ((listData as any[]).length > 0 && !activeBuild) {
        setActiveBuild((listData as any[])[0]);
      }
    } catch (e: any) {
      setError(e?.message || "Failed to load builds");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 4000);
    return () => clearInterval(interval);
  }, [activeBuild?.build_id]);

  async function handleStartBuild(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !description.trim()) {
      toast.error("Please fill in project title and description");
      return;
    }

    setBuilding(true);
    try {
      const newBuild = await api.demos.build({
        title,
        description,
        company_name: company || undefined,
        project_type: projectType,
      });
      toast.success("Demo build started in sandbox!");
      setShowNewForm(false);
      setTitle("");
      setDescription("");
      setCompany("");
      setActiveBuild(newBuild as any);
      await loadData();
    } catch (e: any) {
      toast.error(e?.message || "Failed to start demo build");
    } finally {
      setBuilding(false);
    }
  }

  async function handleRefineBuild(e: React.FormEvent) {
    e.preventDefault();
    if (!activeBuild || !refinePrompt.trim()) return;

    setRefining(true);
    try {
      const updated = await api.demos.refine(activeBuild.build_id, refinePrompt);
      toast.success("Refinement prompt submitted! Updating build...");
      setRefinePrompt("");
      setActiveBuild(updated as any);
      await loadData();
    } catch (e: any) {
      toast.error(e?.message || "Failed to submit refinement request");
    } finally {
      setRefining(false);
    }
  }

  return (
    <PageTransition>
      <Header
        title="AI Demo Studio & Deployment Sandbox"
        description="Generate, verify in Docker, export to GitHub, and deploy live full-stack apps"
        action={
          <div className="flex items-center gap-3">
            {quota && (
              <Badge variant="outline" className="px-3 py-1 text-xs">
                Quota: {quota.used} / {quota.limit} demos used today
              </Badge>
            )}
            <Button size="sm" onClick={() => setShowNewForm(true)} disabled={building}>
              <Plus className="mr-2 h-4 w-4" />
              Build New Demo Idea
            </Button>
          </div>
        }
      />

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error} — check if FastAPI server is running on port 8000.
        </div>
      )}

      {/* New Build Modal/Card */}
      {showNewForm && (
        <Card className="mb-6 border-accent1/30 bg-accent1/5">
          <CardContent className="p-6">
            <form onSubmit={handleStartBuild} className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="font-display text-base text-foreground flex items-center gap-2">
                  <Sparkles className="h-5 w-5 text-accent1" /> Create AI Demo Idea
                </h3>
                <Button type="button" variant="ghost" size="sm" onClick={() => setShowNewForm(false)}>
                  Cancel
                </Button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-medium text-muted-foreground">Demo Title</label>
                  <Input
                    placeholder="e.g. AI Financial Dashboard"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground">Target Company (Optional)</label>
                  <Input
                    placeholder="e.g. Acme Corp"
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground">Stack Type</label>
                <div className="mt-1 flex gap-3">
                  {(["fullstack", "frontend_only", "backend_only"] as const).map((type) => (
                    <button
                      key={type}
                      type="button"
                      onClick={() => setProjectType(type)}
                      className={`rounded-lg border px-3 py-2 text-xs font-medium capitalize transition-colors ${
                        projectType === type
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-border bg-background text-muted-foreground hover:bg-muted"
                      }`}
                    >
                      {type.replace("_", " ")}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground">Prompt & Features Specification</label>
                <Textarea
                  placeholder="Describe the features, layout, and API requirements for the demo project..."
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  required
                />
              </div>

              <Button type="submit" disabled={building} className="w-full">
                {building ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Hammer className="mr-2 h-4 w-4" />}
                Build & Deploy Demo in Sandbox
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Active Workspace / Preview & Refinement Studio */}
      {activeBuild && (
        <div className="mb-8 grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left: Progress & Refinement Studio */}
          <div className="lg:col-span-1 space-y-4">
            <Card className="border-border">
              <CardContent className="p-5 space-y-4">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs text-muted-foreground">{activeBuild.build_id}</span>
                    <Badge
                      variant={
                        activeBuild.stage === "success" && activeBuild.deploy_stage === "deployed"
                          ? "sent"
                          : activeBuild.stage === "failed" || activeBuild.deploy_stage === "deploy_failed"
                          ? "rejected"
                          : "review"
                      }
                    >
                      {activeBuild.deploy_stage || activeBuild.stage}
                    </Badge>
                  </div>
                  <h2 className="mt-1 font-display text-lg text-foreground">{activeBuild.title}</h2>
                  {activeBuild.company_name && (
                    <p className="text-xs text-muted-foreground">Target: {activeBuild.company_name}</p>
                  )}
                </div>

                {/* Progress Steps */}
                <div className="space-y-2 border-t pt-3">
                  <p className="text-xs font-medium text-muted-foreground">Pipeline Execution Steps:</p>

                  <div className="space-y-1.5 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-2">
                        <Code2 className="h-3.5 w-3.5 text-accent1" /> 1. Code Generation & Sandbox
                      </span>
                      {activeBuild.stage === "success" ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                      ) : activeBuild.stage === "failed" ? (
                        <XCircle className="h-4 w-4 text-red-500" />
                      ) : (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" />
                      )}
                    </div>

                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-2">
                        <Terminal className="h-3.5 w-3.5 text-accent1" /> 2. GitHub Export
                      </span>
                      {activeBuild.repo_url ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                      ) : (
                        <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                      )}
                    </div>

                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-2">
                        <Layers className="h-3.5 w-3.5 text-accent1" /> 3. Live Deployment
                      </span>
                      {activeBuild.deploy_stage === "deployed" ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                      ) : activeBuild.deploy_stage === "deploy_failed" ? (
                        <XCircle className="h-4 w-4 text-red-500" />
                      ) : (
                        <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                      )}
                    </div>
                  </div>
                </div>

                {/* Direct Links */}
                <div className="flex flex-wrap gap-2 border-t pt-3">
                  {activeBuild.repo_url && (
                    <a
                      href={activeBuild.repo_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium hover:bg-muted"
                    >
                      <ExternalLink className="h-3 w-3" /> GitHub Repo
                    </a>
                  )}
                  {activeBuild.frontend_url && (
                    <a
                      href={activeBuild.frontend_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 rounded-lg bg-emerald-500/10 px-2.5 py-1.5 text-xs font-medium text-emerald-600 hover:bg-emerald-500/20"
                    >
                      <ExternalLink className="h-3 w-3" /> Frontend URL
                    </a>
                  )}
                  {activeBuild.backend_url && (
                    <a
                      href={activeBuild.backend_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 rounded-lg bg-blue-500/10 px-2.5 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-500/20"
                    >
                      <ExternalLink className="h-3 w-3" /> Backend API
                    </a>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Refinement Chat Studio */}
            <Card>
              <CardContent className="p-5 space-y-3">
                <div>
                  <h4 className="font-display text-sm text-foreground flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-accent1" /> Refine & Edit Demo
                  </h4>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Reviewing the deployment? Request AI revisions (e.g. &quot;Add dark mode button&quot;, &quot;Fix CORS headers&quot;).
                  </p>
                </div>

                <form onSubmit={handleRefineBuild} className="space-y-2">
                  <Textarea
                    placeholder="Enter refinement instructions for the AI builder..."
                    rows={2}
                    value={refinePrompt}
                    onChange={(e) => setRefinePrompt(e.target.value)}
                  />
                  <Button type="submit" size="sm" disabled={refining || !refinePrompt.trim()} className="w-full">
                    {refining ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <Send className="mr-2 h-3.5 w-3.5" />}
                    Submit Refinement & Re-deploy
                  </Button>
                </form>
              </CardContent>
            </Card>
          </div>

          {/* Right: Embedded Live Preview Frame */}
          <div className="lg:col-span-2">
            <Card className="h-full overflow-hidden border-border flex flex-col">
              <div className="flex items-center justify-between border-b bg-muted/40 px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                  <span className="text-xs font-medium text-foreground">Interactive Live Preview</span>
                </div>
                {activeBuild.frontend_url || activeBuild.backend_url ? (
                  <span className="font-mono text-xs text-muted-foreground">
                    {activeBuild.frontend_url || activeBuild.backend_url}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">Waiting for deployment...</span>
                )}
              </div>

              <div className="flex-1 bg-background min-h-[500px]">
                {activeBuild.frontend_url || activeBuild.backend_url ? (
                  <iframe
                    src={activeBuild.frontend_url || activeBuild.backend_url || undefined}
                    className="h-full w-full border-0"
                    title="Live Demo Preview"
                  />
                ) : (
                  <div className="flex h-full min-h-[500px] flex-col items-center justify-center text-center p-6">
                    <Loader2 className="h-8 w-8 animate-spin text-accent1 mb-3" />
                    <p className="text-sm font-medium text-foreground">Building & Deploying Sandbox...</p>
                    <p className="text-xs text-muted-foreground mt-1 max-w-sm">
                      Executing code generation, Docker verification tests, and deploying to Vercel / Cloud Run.
                    </p>
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* Builds History List Table */}
      <div className="space-y-4">
        <h3 className="font-display text-base text-foreground">Demo Builds History</h3>

        {loading ? (
          <div className="flex items-center justify-center py-16 text-muted-foreground">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading builds...
          </div>
        ) : builds.length === 0 ? (
          <div className="rounded-2xl border border-dashed p-12 text-center text-sm text-muted-foreground">
            No demo builds generated yet. Click &quot;Build New Demo Idea&quot; above to create one.
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl border bg-card shadow-elevation-low">
            <table className="w-full">
              <thead>
                <tr className="border-b bg-muted/40">
                  <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Demo Project</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Type</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Status</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Links</th>
                  <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {builds.map((b) => (
                  <tr
                    key={b.build_id}
                    className={`border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30 ${
                      activeBuild?.build_id === b.build_id ? "bg-accent1/5" : ""
                    }`}
                  >
                    <td className="px-5 py-3.5">
                      <p className="text-sm font-medium text-foreground">{b.title || "Untitled Demo"}</p>
                      <p className="font-mono text-xs text-muted-foreground">{b.build_id}</p>
                    </td>
                    <td className="px-5 py-3.5 text-xs text-muted-foreground capitalize">
                      {(b.project_type || "fullstack").replace("_", " ")}
                    </td>
                    <td className="px-5 py-3.5 text-xs">
                      <Badge variant={b.deploy_stage === "deployed" ? "sent" : "review"}>
                        {b.deploy_stage || b.stage}
                      </Badge>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex gap-2">
                        {b.frontend_url && (
                          <a
                            href={b.frontend_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-emerald-600 hover:underline"
                          >
                            Live
                          </a>
                        )}
                        {b.repo_url && (
                          <a
                            href={b.repo_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-accent1 hover:underline"
                          >
                            GitHub
                          </a>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <Button size="sm" variant="outline" onClick={() => setActiveBuild(b)}>
                        Inspect & Refine
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </PageTransition>
  );
}
