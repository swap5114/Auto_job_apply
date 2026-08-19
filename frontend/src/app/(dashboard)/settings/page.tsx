"use client";

import { useEffect, useState } from "react";
import { Save, X, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { api, type SearchCriteria, type PipelineConfig } from "@/lib/api";

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
      onAdd(input.trim().toLowerCase());
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
          {tags.length === 0 && (
            <span className="text-xs text-muted-foreground">None yet</span>
          )}
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

export default function SettingsPage() {
  const [criteria, setCriteria] = useState<SearchCriteria | null>(null);
  const [config, setConfig] = useState<PipelineConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [c, p] = await Promise.all([
        api.settings.getSearchCriteria(),
        api.settings.getPipelineConfig(),
      ]);
      setCriteria(c);
      setConfig(p);
    } catch (e: any) {
      setError(e?.message || "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSave() {
    if (!criteria || !config) return;
    setSaving(true);
    try {
      await Promise.all([
        api.settings.updateSearchCriteria(criteria),
        api.settings.updatePipelineConfig(config),
      ]);
      toast.success("Settings saved");
    } catch (e: any) {
      toast.error(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  // Helpers to update criteria arrays immutably
  function updateList(key: keyof SearchCriteria, updater: (list: string[]) => string[]) {
    setCriteria((c) => (c ? { ...c, [key]: updater((c[key] as string[]) || []) } : c));
  }

  return (
    <PageTransition>
      <Header
        title="Settings"
        description="Configure your pipeline behavior"
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

      {loading || !criteria || !config ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Loading settings…
        </div>
      ) : (
        <div className="pb-16">
          <Tabs defaultValue="criteria" className="space-y-6">
            <TabsList>
              <TabsTrigger value="criteria">Search Criteria</TabsTrigger>
              <TabsTrigger value="pipeline">Pipeline Config</TabsTrigger>
            </TabsList>

            {/* Search Criteria */}
            <TabsContent value="criteria" className="space-y-6">
              <Card>
                <CardContent className="space-y-6 p-6">
                  <TagInput
                    label="Role Keywords (a lead must match one)"
                    tags={criteria.role_keywords}
                    onAdd={(t) => updateList("role_keywords", (l) => [...l, t])}
                    onRemove={(t) => updateList("role_keywords", (l) => l.filter((x) => x !== t))}
                    placeholder="e.g. software engineer, backend developer…"
                  />
                  <Separator />
                  <TagInput
                    label="Tech Stack Keywords (a lead must match one)"
                    tags={criteria.tech_stack_keywords}
                    onAdd={(t) => updateList("tech_stack_keywords", (l) => [...l, t])}
                    onRemove={(t) => updateList("tech_stack_keywords", (l) => l.filter((x) => x !== t))}
                    placeholder="e.g. react, node, python…"
                  />
                  <Separator />
                  <TagInput
                    label="Seniority Exclusions"
                    tags={criteria.seniority_exclude_keywords}
                    onAdd={(t) => updateList("seniority_exclude_keywords", (l) => [...l, t])}
                    onRemove={(t) => updateList("seniority_exclude_keywords", (l) => l.filter((x) => x !== t))}
                    placeholder="e.g. senior, lead, principal…"
                  />
                  <Separator />
                  <TagInput
                    label="Non-Tech Exclusions"
                    tags={criteria.non_tech_exclude_keywords}
                    onAdd={(t) => updateList("non_tech_exclude_keywords", (l) => [...l, t])}
                    onRemove={(t) => updateList("non_tech_exclude_keywords", (l) => l.filter((x) => x !== t))}
                    placeholder="e.g. operations, sales, admin…"
                  />
                  <Separator />
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-foreground">Experience Threshold</label>
                    <p className="text-xs text-muted-foreground">
                      Exclude jobs requiring more than this many years of experience
                    </p>
                    <Input
                      type="number"
                      value={criteria.years_experience_threshold}
                      onChange={(e) =>
                        setCriteria((c) => (c ? { ...c, years_experience_threshold: Number(e.target.value) } : c))
                      }
                      min={0}
                      max={10}
                      className="w-24"
                    />
                  </div>
                  <Separator />
                  <TagInput
                    label="Location Keywords (informational)"
                    tags={criteria.location_keywords}
                    onAdd={(t) => updateList("location_keywords", (l) => [...l, t])}
                    onRemove={(t) => updateList("location_keywords", (l) => l.filter((x) => x !== t))}
                    placeholder="e.g. remote, india, usa…"
                  />
                </CardContent>
              </Card>
            </TabsContent>

            {/* Pipeline Config */}
            <TabsContent value="pipeline" className="space-y-6">
              <Card>
                <CardContent className="space-y-6 p-6">
                  {/* LLM Backend */}
                  <div className="space-y-3">
                    <label className="text-sm font-medium text-foreground">LLM Backend</label>
                    <div className="flex gap-3">
                      {(["claude", "gemini"] as const).map((backend) => (
                        <button
                          key={backend}
                          onClick={() => setConfig((c) => (c ? { ...c, model_backend: backend } : c))}
                          className={`rounded-lg border px-4 py-2.5 text-sm font-medium capitalize transition-colors ${config.model_backend === backend
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-border bg-background text-muted-foreground hover:bg-muted"
                            }`}
                        >
                          {backend === "claude" ? "Claude (API)" : "Gemini (Free)"}
                        </button>
                      ))}
                    </div>
                  </div>

                  <Separator />

                  <div className="grid grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-foreground">Follow-up Days</label>
                      <p className="text-xs text-muted-foreground">Days to wait before a follow-up</p>
                      <Input
                        type="number"
                        value={config.followup_days}
                        onChange={(e) => setConfig((c) => (c ? { ...c, followup_days: Number(e.target.value) } : c))}
                        min={1}
                        max={30}
                        className="w-24"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-foreground">Max Follow-ups</label>
                      <p className="text-xs text-muted-foreground">Max follow-up messages per lead</p>
                      <Input
                        type="number"
                        value={config.max_followups}
                        onChange={(e) => setConfig((c) => (c ? { ...c, max_followups: Number(e.target.value) } : c))}
                        min={0}
                        max={5}
                        className="w-24"
                      />
                    </div>
                  </div>

                  <Separator />

                  {/* Gmail Mode */}
                  <div className="space-y-3">
                    <label className="text-sm font-medium text-foreground">Gmail Mode</label>
                    <p className="text-xs text-muted-foreground">
                      Create drafts for manual review, or send directly on approval
                    </p>
                    <div className="flex gap-3">
                      <button
                        onClick={() => setConfig((c) => (c ? { ...c, gmail_direct_send: false } : c))}
                        className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${!config.gmail_direct_send
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-background text-muted-foreground hover:bg-muted"
                          }`}
                      >
                        Drafts Only
                      </button>
                      <button
                        onClick={() => setConfig((c) => (c ? { ...c, gmail_direct_send: true } : c))}
                        className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${config.gmail_direct_send
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-background text-muted-foreground hover:bg-muted"
                          }`}
                      >
                        Direct Send
                      </button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      )}
    </PageTransition>
  );
}
