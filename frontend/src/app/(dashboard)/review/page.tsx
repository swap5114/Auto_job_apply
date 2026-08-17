"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Edit3, XCircle, ChevronDown, Inbox } from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";

const mockPendingLeads = [
  {
    id: "g7h8i9", company: "TechFlow", role: "Full Stack Developer", source: "arbeitnow",
    resume_version: "swapnil_jain_resume_techflow",
    outreach_draft:
      "Subject: Re: Full Stack role at TechFlow\n\nHi TechFlow team,\n\nYour real-time data pipeline platform caught my attention — the challenge of processing streams at scale is exactly what excites me. I built something similar with my Artha.ai project (FastAPI + async pipelines, 99% data availability via multi-source fallback chains).\n\nHappy to chat about how I'd approach your stack. Here's my work: github.com/swap5114\n\nSwapnil",
    resume_highlights: ["FastAPI + async pipelines", "MERN stack", "Real-time data"],
  },
  {
    id: "j1k2l3", company: "Migma AI", role: "Backend Product Engineer", source: "careers_page",
    resume_version: "swapnil_jain_resume_migma",
    outreach_draft:
      "Subject: Thoughts on your backend eng search\n\nHi Migma team,\n\nYour work on real-time AI inference infrastructure is compelling — particularly the distributed systems angle. My current project (LangGraph-orchestrated multi-agent pipeline) tackles a similar coordination problem.\n\nI'd love to discuss how I'd contribute to your platform's scaling challenges.\n\ngithub.com/swap5114\nSwapnil",
    resume_highlights: ["LangGraph orchestration", "Python/FastAPI", "Distributed systems"],
  },
  {
    id: "x9y8z7", company: "", role: "", source: "x", x_handle: "hiringdev",
    resume_version: "swapnil_jain_resume_hiringdev",
    outreach_draft:
      "Hey! Saw you're looking for a junior full-stack dev. I ship fast — just built a multi-agent pipeline (Python + LangGraph) and a real-time trading platform (Next.js + FastAPI). Open to chat?",
    resume_highlights: ["Full-stack (MERN)", "Python + LangGraph", "Ships fast"],
  },
];

export default function ReviewPage() {
  const [leads, setLeads] = useState(mockPendingLeads);
  const [expandedId, setExpandedId] = useState<string | null>(mockPendingLeads[0]?.id || null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");

  const total = mockPendingLeads.length;
  const done = total - leads.length;
  const progress = total > 0 ? (done / total) * 100 : 0;

  function handleApprove(id: string) {
    setLeads((prev) => prev.filter((l) => l.id !== id));
  }
  function handleReject(id: string) {
    setLeads((prev) => prev.filter((l) => l.id !== id));
  }
  function handleEdit(id: string) {
    const lead = leads.find((l) => l.id === id);
    if (lead) {
      setEditingId(id);
      setEditDraft(lead.outreach_draft);
    }
  }
  function handleSaveEdit(id: string) {
    setLeads((prev) => prev.filter((l) => l.id !== id));
    setEditingId(null);
  }

  return (
    <PageTransition>
      <Header
        title="Review Queue"
        description={`${leads.length} of ${total} leads pending your approval`}
      />

      {/* Progress bar */}
      <div className="mb-6">
        <div className="mb-1.5 flex items-center justify-between text-xs text-muted-foreground">
          <span>Reviewed {done} of {total}</span>
          <span>{Math.round(progress)}%</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <motion.div
            className="h-full rounded-full accent-gradient"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ type: "spring", stiffness: 200, damping: 30 }}
          />
        </div>
      </div>

      <div className="space-y-4 pb-16">
        {leads.length === 0 && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex flex-col items-center justify-center rounded-2xl border border-dashed py-24"
          >
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50">
              <CheckCircle2 className="h-7 w-7 text-emerald-600" />
            </div>
            <h3 className="mt-4 font-display text-xl text-foreground">All caught up</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              No leads pending review right now.
            </p>
          </motion.div>
        )}

        <AnimatePresence mode="popLayout">
          {leads.map((lead) => {
            const isExpanded = expandedId === lead.id;
            const isEditing = editingId === lead.id;
            const displayName = lead.company || `@${lead.x_handle}`;

            return (
              <motion.div
                key={lead.id}
                layout
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: -120, transition: { duration: 0.3 } }}
                transition={{ duration: 0.3 }}
              >
                <Card className={isExpanded ? "ring-1 ring-accent1/30" : "transition-shadow hover:shadow-dropdown"}>
                  <div
                    className="flex cursor-pointer items-center justify-between px-6 py-4"
                    onClick={() => setExpandedId(isExpanded ? null : lead.id)}
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted font-display text-sm text-muted-foreground">
                        {displayName.charAt(lead.company ? 0 : 1).toUpperCase()}
                      </div>
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          {displayName}
                          {lead.role && <span className="text-muted-foreground"> — {lead.role}</span>}
                        </p>
                        <p className="text-xs text-muted-foreground">from: {lead.source}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="review">Pending</Badge>
                      <ChevronDown
                        className={`h-4 w-4 text-muted-foreground transition-transform ${isExpanded ? "rotate-180" : ""}`}
                      />
                    </div>
                  </div>

                  <AnimatePresence>
                    {isExpanded && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.25 }}
                        className="overflow-hidden"
                      >
                        <Separator />
                        <CardContent className="space-y-5 p-6">
                          <div>
                            <p className="mb-2 text-xs font-medium text-muted-foreground">
                              Resume Highlights
                            </p>
                            <div className="flex flex-wrap gap-2">
                              {lead.resume_highlights.map((h) => (
                                <span key={h} className="rounded-md bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                                  {h}
                                </span>
                              ))}
                            </div>
                            <p className="mt-2 font-mono text-xs text-muted-foreground">
                              {lead.resume_version}.pdf
                            </p>
                          </div>

                          <div>
                            <p className="mb-2 text-xs font-medium text-muted-foreground">
                              Outreach Draft
                            </p>
                            {isEditing ? (
                              <div className="space-y-3">
                                <Textarea
                                  value={editDraft}
                                  onChange={(e) => setEditDraft(e.target.value)}
                                  className="min-h-[180px] text-sm"
                                />
                                <div className="flex gap-2">
                                  <Button size="sm" onClick={() => handleSaveEdit(lead.id)}>
                                    Save & Approve
                                  </Button>
                                  <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                                    Cancel
                                  </Button>
                                </div>
                              </div>
                            ) : (
                              <div className="rounded-xl border bg-muted/20 p-4">
                                <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                                  {lead.outreach_draft}
                                </pre>
                              </div>
                            )}
                          </div>

                          {!isEditing && (
                            <div className="flex gap-3 pt-1">
                              <Button
                                size="sm"
                                onClick={() => handleApprove(lead.id)}
                                className="bg-emerald-600 shadow-none hover:bg-emerald-700"
                              >
                                <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
                                Approve
                              </Button>
                              <Button size="sm" variant="outline" onClick={() => handleEdit(lead.id)}>
                                <Edit3 className="mr-1.5 h-3.5 w-3.5" />
                                Edit
                              </Button>
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => handleReject(lead.id)}
                                className="shadow-none"
                              >
                                <XCircle className="mr-1.5 h-3.5 w-3.5" />
                                Reject
                              </Button>
                            </div>
                          )}
                        </CardContent>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </Card>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </PageTransition>
  );
}
