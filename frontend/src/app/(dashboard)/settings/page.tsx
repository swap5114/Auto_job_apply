"use client";

import { useState } from "react";
import { Save, X, Plus } from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";

// Tag Input Component
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
        <div className="flex flex-wrap gap-2 mb-2">
          {tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded-md bg-secondary px-2.5 py-1 text-xs font-medium text-secondary-foreground"
            >
              {tag}
              <button
                onClick={() => onRemove(tag)}
                className="ml-0.5 rounded-sm hover:bg-muted-foreground/20"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || "Type and press Enter to add"}
          className="border-0 p-0 h-8 focus-visible:ring-0 focus-visible:ring-offset-0"
        />
      </div>
    </div>
  );
}

export default function SettingsPage() {
  // Search criteria state
  const [roleKeywords, setRoleKeywords] = useState([
    "developer", "engineer", "react", "python", "full stack", "backend", "frontend", "node", "javascript",
  ]);
  const [seniorityExclusions, setSeniorityExclusions] = useState([
    "senior", "lead", "principal", "staff", "manager", "director",
  ]);
  const [locationKeywords, setLocationKeywords] = useState([
    "remote", "india", "usa", "europe", "uk",
  ]);
  const [yearsThreshold, setYearsThreshold] = useState(1);

  // Pipeline config state
  const [llmBackend, setLlmBackend] = useState<"claude" | "ollama">("claude");
  const [followupDays, setFollowupDays] = useState(5);
  const [maxFollowups, setMaxFollowups] = useState(2);
  const [gmailMode, setGmailMode] = useState<"drafts" | "direct">("drafts");

  return (
    <PageTransition>
      <Header
        title="Settings"
        description="Configure your pipeline behavior"
        action={
          <Button size="sm">
            <Save className="mr-2 h-3.5 w-3.5" />
            Save Changes
          </Button>
        }
      />

      <div className="pb-16">
        <Tabs defaultValue="criteria" className="space-y-6">
          <TabsList>
            <TabsTrigger value="criteria">Search Criteria</TabsTrigger>
            <TabsTrigger value="pipeline">Pipeline Config</TabsTrigger>
          </TabsList>

          {/* Search Criteria Tab */}
          <TabsContent value="criteria" className="space-y-6">
            <Card>
              <CardContent className="p-6 space-y-6">
                <TagInput
                  label="Role Keywords"
                  tags={roleKeywords}
                  onAdd={(tag) => setRoleKeywords((prev) => [...prev, tag])}
                  onRemove={(tag) =>
                    setRoleKeywords((prev) => prev.filter((t) => t !== tag))
                  }
                  placeholder="e.g. developer, react, python..."
                />

                <Separator />

                <TagInput
                  label="Seniority Exclusions"
                  tags={seniorityExclusions}
                  onAdd={(tag) => setSeniorityExclusions((prev) => [...prev, tag])}
                  onRemove={(tag) =>
                    setSeniorityExclusions((prev) => prev.filter((t) => t !== tag))
                  }
                  placeholder="e.g. senior, lead, principal..."
                />

                <Separator />

                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">
                    Experience Threshold
                  </label>
                  <p className="text-xs text-muted-foreground">
                    Exclude jobs requiring more than this many years of experience
                  </p>
                  <Input
                    type="number"
                    value={yearsThreshold}
                    onChange={(e) => setYearsThreshold(Number(e.target.value))}
                    min={0}
                    max={10}
                    className="w-24"
                  />
                </div>

                <Separator />

                <TagInput
                  label="Location Keywords"
                  tags={locationKeywords}
                  onAdd={(tag) => setLocationKeywords((prev) => [...prev, tag])}
                  onRemove={(tag) =>
                    setLocationKeywords((prev) => prev.filter((t) => t !== tag))
                  }
                  placeholder="e.g. remote, india, usa..."
                />
              </CardContent>
            </Card>
          </TabsContent>

          {/* Pipeline Config Tab */}
          <TabsContent value="pipeline" className="space-y-6">
            <Card>
              <CardContent className="p-6 space-y-6">
                {/* LLM Backend */}
                <div className="space-y-3">
                  <label className="text-sm font-medium text-foreground">
                    LLM Backend
                  </label>
                  <div className="flex gap-3">
                    <button
                      onClick={() => setLlmBackend("claude")}
                      className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${llmBackend === "claude"
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-border bg-background text-muted-foreground hover:bg-muted"
                        }`}
                    >
                      Claude (API)
                    </button>
                    <button
                      onClick={() => setLlmBackend("ollama")}
                      className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${llmBackend === "ollama"
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-border bg-background text-muted-foreground hover:bg-muted"
                        }`}
                    >
                      Ollama (Local)
                    </button>
                  </div>
                </div>

                <Separator />

                {/* Follow-up Settings */}
                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-foreground">
                      Follow-up Days
                    </label>
                    <p className="text-xs text-muted-foreground">
                      Days to wait before sending a follow-up
                    </p>
                    <Input
                      type="number"
                      value={followupDays}
                      onChange={(e) => setFollowupDays(Number(e.target.value))}
                      min={1}
                      max={30}
                      className="w-24"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-foreground">
                      Max Follow-ups
                    </label>
                    <p className="text-xs text-muted-foreground">
                      Maximum follow-up messages per lead
                    </p>
                    <Input
                      type="number"
                      value={maxFollowups}
                      onChange={(e) => setMaxFollowups(Number(e.target.value))}
                      min={0}
                      max={5}
                      className="w-24"
                    />
                  </div>
                </div>

                <Separator />

                {/* Gmail Mode */}
                <div className="space-y-3">
                  <label className="text-sm font-medium text-foreground">
                    Gmail Mode
                  </label>
                  <p className="text-xs text-muted-foreground">
                    Choose whether to create drafts for manual review or send directly
                  </p>
                  <div className="flex gap-3">
                    <button
                      onClick={() => setGmailMode("drafts")}
                      className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${gmailMode === "drafts"
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-border bg-background text-muted-foreground hover:bg-muted"
                        }`}
                    >
                      Drafts Only
                    </button>
                    <button
                      onClick={() => setGmailMode("direct")}
                      className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${gmailMode === "direct"
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
    </PageTransition>
  );
}
