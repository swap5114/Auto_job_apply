"use client";

import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle2,
  Edit3,
  XCircle,
  ChevronDown,
  Loader2,
  RefreshCw,
  FileText,
  ExternalLink,
  Send,
} from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, type Lead } from "@/lib/api";

export default function ReviewPage() {
  const [tab, setTab] = useState<"outreach" | "apply">("outreach");

  // Outreach queue: pending_review + in_review leads carrying an
  // outreach_draft. Apply queue: any of pending_review / in_review /
  // ready_to_apply leads whose channel includes "apply" -- ready_to_apply
  // leads stay visible here (unlike outreach's approved leads, which
  // disappear once sent) because the Apply channel's post-approval
  // actions (the deep link, "Mark as Applied") live on this same page,
  // not a separate one.
  const [allLeads, setAllLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [pending, inReview, readyToApply, applied] = await Promise.all([
        api.leads.list("pending_review"),
        api.leads.list("in_review"),
        api.leads.list("ready_to_apply"),
        api.leads.list("applied"),
      ]);
      setAllLeads([...pending, ...inReview, ...readyToApply, ...applied]);
    } catch (e: any) {
      setError(e?.message || "Failed to load review queue");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const outreachLeads = useMemo(
    () =>
      allLeads.filter(
        (l) => (l.status === "pending_review" || l.status === "in_review") && !!l.outreach_draft
      ),
    [allLeads]
  );

  const applyLeads = useMemo(
    () => allLeads.filter((l) => (l.channel || []).includes("apply")),
    [allLeads]
  );

  return (
    <PageTransition>
      <Header
        title="Review Queue"
        description={
          tab === "outreach"
            ? `${outreachLeads.length} outreach drafts pending your approval`
            : `${applyLeads.length} apply-channel leads in progress`
        }
        action={
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        }
      />

      <Tabs value={tab} onValueChange={(v) => setTab(v as "outreach" | "apply")} className="mb-5">
        <TabsList>
          <TabsTrigger value="outreach">Outreach</TabsTrigger>
          <TabsTrigger value="apply">Apply</TabsTrigger>
        </TabsList>
      </Tabs>

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error} — is the API running on port 8000?
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Loading review queue…
        </div>
      ) : tab === "outreach" ? (
        <OutreachQueue leads={outreachLeads} onChanged={load} />
      ) : (
        <ApplyQueue leads={applyLeads} onChanged={load} />
      )}
    </PageTransition>
  );
}

// ---------------------------------------------------------------------------
// Outreach queue (pre-existing behavior, unchanged)
// ---------------------------------------------------------------------------

function OutreachQueue({ leads, onChanged }: { leads: Lead[]; onChanged: () => void }) {
  const [items, setItems] = useState<Lead[]>(leads);
  const [expandedId, setExpandedId] = useState<string | null>(leads[0]?.id ?? null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    setItems(leads);
    setExpandedId(leads[0]?.id ?? null);
  }, [leads]);

  async function handleApprove(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.leads.approve(lead.id, "outreach");
      toast.success(`Approved ${lead.company || lead.x_handle || "lead"}`);
      setItems((prev) => prev.filter((l) => l.id !== lead.id));
      onChanged();
    } catch (e: any) {
      toast.error(e?.message || "Approve failed");
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.leads.reject(lead.id, "outreach");
      toast.success(`Rejected ${lead.company || lead.x_handle || "lead"}`);
      setItems((prev) => prev.filter((l) => l.id !== lead.id));
      onChanged();
    } catch (e: any) {
      toast.error(e?.message || "Reject failed");
    } finally {
      setBusyId(null);
    }
  }

  async function handleSaveEdit(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.leads.edit(lead.id, editDraft);
      toast.success("Draft updated & approved");
      setItems((prev) => prev.filter((l) => l.id !== lead.id));
      setEditingId(null);
      onChanged();
    } catch (e: any) {
      toast.error(e?.message || "Edit failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4 pb-16">
      {items.length === 0 && (
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
            No outreach drafts pending review right now. Run the pipeline to queue more.
          </p>
        </motion.div>
      )}

      <AnimatePresence mode="popLayout">
        {items.map((lead) => {
          const isExpanded = expandedId === lead.id;
          const isEditing = editingId === lead.id;
          const displayName = lead.company || `@${lead.x_handle}`;
          const busy = busyId === lead.id;

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
                        {lead.resume_version && (
                          <div>
                            <p className="mb-2 text-xs font-medium text-muted-foreground">
                              Tailored Resume
                            </p>
                            <p className="font-mono text-xs text-muted-foreground">
                              {lead.resume_version}.pdf
                            </p>
                          </div>
                        )}

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
                                <Button size="sm" disabled={busy} onClick={() => handleSaveEdit(lead)}>
                                  {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save & Approve"}
                                </Button>
                                <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                                  Cancel
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <div className="rounded-xl border bg-muted/20 p-4">
                              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                                {lead.outreach_draft || "No draft yet."}
                              </pre>
                            </div>
                          )}
                        </div>

                        {!isEditing && (
                          <div className="flex gap-3 pt-1">
                            <Button
                              size="sm"
                              disabled={busy}
                              onClick={() => handleApprove(lead)}
                              className="bg-emerald-600 shadow-none hover:bg-emerald-700"
                            >
                              {busy ? (
                                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
                              )}
                              Approve
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setEditingId(lead.id);
                                setEditDraft(lead.outreach_draft || "");
                              }}
                            >
                              <Edit3 className="mr-1.5 h-3.5 w-3.5" />
                              Edit
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              disabled={busy}
                              onClick={() => handleReject(lead)}
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
  );
}

// ---------------------------------------------------------------------------
// Apply queue (Phase 5.4) -- tailored resume + cover note review, then a
// real deep link to the listing plus "Mark as Applied".
// ---------------------------------------------------------------------------

const APPLY_STAGE_LABEL: Record<string, string> = {
  matched: "Preparing",
  tailoring: "Preparing",
  pending_review: "Needs Review",
  in_review: "Needs Review",
  ready_to_apply: "Ready to Apply",
  applied: "Applied",
};

function ApplyQueue({ leads, onChanged }: { leads: Lead[]; onChanged: () => void }) {
  const [expandedId, setExpandedId] = useState<string | null>(leads[0]?.id ?? null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editNote, setEditNote] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [resumeUrls, setResumeUrls] = useState<Record<string, string>>({});

  useEffect(() => {
    setExpandedId(leads[0]?.id ?? null);
    // Revoke any previously-created blob URLs before the lead list changes
    // out from under them, so we don't leak memory across refreshes.
    return () => {
      Object.values(resumeUrls).forEach((url) => URL.revokeObjectURL(url));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leads]);

  async function handleViewResume(lead: Lead) {
    if (resumeUrls[lead.id]) {
      window.open(resumeUrls[lead.id], "_blank");
      return;
    }
    try {
      const url = await api.leads.getResumePdfBlobUrl(lead.id);
      setResumeUrls((prev) => ({ ...prev, [lead.id]: url }));
      window.open(url, "_blank");
    } catch (e: any) {
      toast.error(e?.message || "Couldn't load the tailored resume PDF");
    }
  }

  async function handleApprove(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.leads.approve(lead.id, "apply");
      toast.success(`Approved ${lead.company || "lead"} — ready to apply`);
      onChanged();
    } catch (e: any) {
      toast.error(e?.message || "Approve failed");
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.leads.reject(lead.id, "apply");
      toast.success(`Rejected ${lead.company || "lead"}`);
      onChanged();
    } catch (e: any) {
      toast.error(e?.message || "Reject failed");
    } finally {
      setBusyId(null);
    }
  }

  async function handleSaveEdit(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.leads.editCoverNote(lead.id, editNote);
      toast.success("Cover note updated & approved — ready to apply");
      setEditingId(null);
      onChanged();
    } catch (e: any) {
      toast.error(e?.message || "Edit failed");
    } finally {
      setBusyId(null);
    }
  }

  async function handleMarkApplied(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.leads.markApplied(lead.id);
      toast.success(`Marked ${lead.company || "lead"} as applied`);
      onChanged();
    } catch (e: any) {
      toast.error(e?.message || "Failed to mark as applied");
    } finally {
      setBusyId(null);
    }
  }

  if (leads.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="flex flex-col items-center justify-center rounded-2xl border border-dashed py-24"
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50">
          <CheckCircle2 className="h-7 w-7 text-emerald-600" />
        </div>
        <h3 className="mt-4 font-display text-xl text-foreground">Nothing here yet</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          No apply-channel leads in progress. Save a matched job with the Apply channel to get started.
        </p>
      </motion.div>
    );
  }

  return (
    <div className="space-y-4 pb-16">
      <AnimatePresence mode="popLayout">
        {leads.map((lead) => {
          const isExpanded = expandedId === lead.id;
          const isEditing = editingId === lead.id;
          const busy = busyId === lead.id;
          const stageLabel = APPLY_STAGE_LABEL[lead.status] || lead.status || "Preparing";
          const needsReview = lead.status === "pending_review" || lead.status === "in_review";
          const isReadyToApply = lead.status === "ready_to_apply";
          const isApplied = lead.status === "applied";

          return (
            <motion.div
              key={lead.id}
              layout
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <Card className={isExpanded ? "ring-1 ring-accent1/30" : "transition-shadow hover:shadow-dropdown"}>
                <div
                  className="flex cursor-pointer items-center justify-between px-6 py-4"
                  onClick={() => setExpandedId(isExpanded ? null : lead.id)}
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted font-display text-sm text-muted-foreground">
                      {(lead.company || "?").charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        {lead.company}
                        {lead.role && <span className="text-muted-foreground"> — {lead.role}</span>}
                      </p>
                      <p className="text-xs text-muted-foreground">from: {lead.source}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={isApplied ? "sent" : isReadyToApply ? "approved" : "review"}>
                      {stageLabel}
                    </Badge>
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
                        {lead.resume_version && (
                          <div>
                            <p className="mb-2 text-xs font-medium text-muted-foreground">
                              Tailored Resume
                            </p>
                            <Button size="sm" variant="outline" onClick={() => handleViewResume(lead)}>
                              <FileText className="mr-1.5 h-3.5 w-3.5" />
                              View resume PDF
                            </Button>
                          </div>
                        )}

                        <div>
                          <p className="mb-2 text-xs font-medium text-muted-foreground">
                            Cover Note
                          </p>
                          {isEditing ? (
                            <div className="space-y-3">
                              <Textarea
                                value={editNote}
                                onChange={(e) => setEditNote(e.target.value)}
                                className="min-h-[180px] text-sm"
                              />
                              <div className="flex gap-2">
                                <Button size="sm" disabled={busy} onClick={() => handleSaveEdit(lead)}>
                                  {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save & Approve"}
                                </Button>
                                <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                                  Cancel
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <div className="rounded-xl border bg-muted/20 p-4">
                              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                                {lead.cover_note || "No cover note yet."}
                              </pre>
                            </div>
                          )}
                        </div>

                        {needsReview && !isEditing && (
                          <div className="flex gap-3 pt-1">
                            <Button
                              size="sm"
                              disabled={busy}
                              onClick={() => handleApprove(lead)}
                              className="bg-emerald-600 shadow-none hover:bg-emerald-700"
                            >
                              {busy ? (
                                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
                              )}
                              Approve
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setEditingId(lead.id);
                                setEditNote(lead.cover_note || "");
                              }}
                            >
                              <Edit3 className="mr-1.5 h-3.5 w-3.5" />
                              Edit
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              disabled={busy}
                              onClick={() => handleReject(lead)}
                              className="shadow-none"
                            >
                              <XCircle className="mr-1.5 h-3.5 w-3.5" />
                              Reject
                            </Button>
                          </div>
                        )}

                        {(isReadyToApply || isApplied) && (
                          <>
                            <Separator />
                            <div className="flex flex-wrap gap-3 pt-1">
                              {lead.listing_url ? (
                                <Button asChild className="bg-accent1 shadow-none hover:bg-accent1/90">
                                  <a href={lead.listing_url} target="_blank" rel="noopener noreferrer">
                                    <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                                    Apply on {lead.domain || "listing"}
                                  </a>
                                </Button>
                              ) : (
                                <p className="text-sm text-muted-foreground">
                                  No listing link available for this lead.
                                </p>
                              )}
                              {isApplied ? (
                                <Badge variant="sent" className="self-center">
                                  <Send className="mr-1.5 h-3 w-3" />
                                  Applied {lead.applied_at ? `· ${new Date(lead.applied_at).toLocaleDateString()}` : ""}
                                </Badge>
                              ) : (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  disabled={busy}
                                  onClick={() => handleMarkApplied(lead)}
                                >
                                  {busy ? (
                                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
                                  )}
                                  Mark as Applied
                                </Button>
                              )}
                            </div>
                          </>
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
  );
}
