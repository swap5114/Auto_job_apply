"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { FileText, ChevronRight, Sparkles, Loader2, RefreshCw, Search, Mail, User, Briefcase } from "lucide-react";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { ResearchPanel } from "@/components/leads/research-panel";
import { RunPipelineDialog } from "@/components/pipeline/run-pipeline-dialog";
import { staggerContainer, slideInLeft } from "@/lib/motion";
import { api, type Lead } from "@/lib/api";
import { stripHtmlToText } from "@/lib/utils";

const statusVariantMap: Record<string, "new" | "review" | "approved" | "sent" | "replied" | "rejected"> = {
  new: "new", pending_review: "review", in_review: "review", approved: "approved",
  sent: "sent", draft_created: "sent", replied: "replied", rejected: "rejected",
};

const statusDot: Record<string, string> = {
  new: "bg-slate-400", pending_review: "bg-amber-500", in_review: "bg-amber-500",
  approved: "bg-blue-500", sent: "bg-emerald-500", draft_created: "bg-emerald-500",
  replied: "bg-violet-500", rejected: "bg-red-500",
};

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    new: "New", pending_review: "In Review", in_review: "In Review",
    approved: "Approved", sent: "Sent", draft_created: "Draft",
    replied: "Replied", rejected: "Rejected",
    approved_needs_gmail: "Needs Gmail", send_skipped: "Not sent", send_failed: "Send failed",
  };
  return labels[status] || status || "New";
}

const FAILURE_LABELS: Record<string, string> = {
  no_contact_found: "No contact email found",
  no_job_description: "No job description",
  tailor_failed: "Resume tailoring failed",
  draft_failed: "Draft generation failed",
  send_failed: "Send failed",
};

function failureLabel(reason?: string) {
  if (!reason) return "";
  return FAILURE_LABELS[reason] || reason.replace(/_/g, " ");
}

const filters = [
  { key: "all", label: "All" },
  { key: "new", label: "New" },
  { key: "pending_review", label: "In Review" },
  { key: "sent", label: "Sent" },
  { key: "replied", label: "Replied" },
  { key: "rejected", label: "Rejected" },
];

export default function LeadsPage() {
  return (
    <Suspense>
      <LeadsPageInner />
    </Suspense>
  );
}

function LeadsPageInner() {
  const searchParams = useSearchParams();
  const deepLinkLeadId = searchParams.get("lead");

  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [scrapeOpen, setScrapeOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setLeads(await api.leads.list());
    } catch (e: any) {
      setError(e?.message || "Failed to load leads");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  // Deep-link from the Builds page (?lead=<id>) — open that lead's detail
  // sheet (on the Research tab) once its data has loaded.
  useEffect(() => {
    if (!deepLinkLeadId || leads.length === 0) return;
    const match = leads.find((l) => l.id === deepLinkLeadId);
    if (match) openLead(match);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkLeadId, leads]);

  const filteredLeads = useMemo(() => {
    if (filter === "all") return leads;
    if (filter === "pending_review")
      return leads.filter((l) => l.status === "pending_review" || l.status === "in_review");
    if (filter === "sent")
      return leads.filter((l) => l.status === "sent" || l.status === "draft_created");
    if (filter === "new")
      return leads.filter((l) => !l.status || l.status === "new");
    return leads.filter((l) => l.status === filter);
  }, [filter, leads]);

  function countFor(key: string) {
    if (key === "all") return leads.length;
    if (key === "pending_review")
      return leads.filter((l) => l.status === "pending_review" || l.status === "in_review").length;
    if (key === "sent")
      return leads.filter((l) => l.status === "sent" || l.status === "draft_created").length;
    if (key === "new") return leads.filter((l) => !l.status || l.status === "new").length;
    return leads.filter((l) => l.status === key).length;
  }

  async function doAction(kind: "approve" | "reject" | "edit", lead: Lead) {
    setActionBusy(true);
    try {
      if (kind === "approve") {
        await api.leads.approve(lead.id);
        toast.success(`Approved ${lead.company || lead.x_handle || "lead"}`);
      } else if (kind === "reject") {
        await api.leads.reject(lead.id);
        toast.success(`Rejected ${lead.company || lead.x_handle || "lead"}`);
      } else if (kind === "edit") {
        await api.leads.edit(lead.id, editDraft);
        toast.success("Draft updated & approved");
      }
      setSelectedLead(null);
      setEditing(false);
      await load();
    } catch (e: any) {
      toast.error(e?.message || "Action failed");
    } finally {
      setActionBusy(false);
    }
  }

  function openLead(lead: Lead) {
    setSelectedLead(lead);
    setEditing(false);
    setEditDraft(lead.outreach_draft || "");
  }

  async function doRetry(lead: Lead) {
    setActionBusy(true);
    try {
      await api.leads.retry(lead.id);
      toast.success(`Retrying ${lead.company || lead.x_handle || "lead"}…`);
      setSelectedLead(null);
      await load();
    } catch (e: any) {
      toast.error(e?.message || "Retry failed");
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <PageTransition>
      <Header
        title="Leads"
        description="All sourced job opportunities"
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={load} disabled={loading}>
              <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button size="sm" onClick={() => setScrapeOpen(true)}>
              <Search className="mr-2 h-3.5 w-3.5" />
              Scrape New
            </Button>
          </div>
        }
      />

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error} — is the API running on port 8000?
        </div>
      )}

      {/* Filters */}
      <div className="mb-5 flex flex-wrap gap-1.5">
        {filters.map((f) => {
          const isActive = filter === f.key;
          return (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`relative rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${isActive ? "text-white" : "text-muted-foreground hover:text-foreground"
                }`}
            >
              {isActive && (
                <motion.div
                  layoutId="leads-filter-pill"
                  className="absolute inset-0 rounded-full accent-gradient"
                  transition={{ type: "spring", stiffness: 500, damping: 38 }}
                />
              )}
              <span className="relative z-10">
                {f.label}
                <span className={`ml-1.5 ${isActive ? "text-white/70" : "text-muted-foreground/60"}`}>
                  {countFor(f.key)}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Loading leads…
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-border/70 bg-card shadow-card">
          <table className="w-full">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Source</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Company</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Designation / Role</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Contact Email</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Status</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Date</th>
                <th className="w-10 px-5 py-3" />
              </tr>
            </thead>
            <motion.tbody key={filter} variants={staggerContainer(0.04)} initial="hidden" animate="show">
              <AnimatePresence mode="popLayout">
                {filteredLeads.map((lead) => (
                  <motion.tr
                    key={lead.id}
                    variants={slideInLeft}
                    layout
                    exit={{ opacity: 0 }}
                    className="group cursor-pointer border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                    onClick={() => openLead(lead)}
                  >
                    <td className="px-5 py-3.5">
                      <span className="rounded-md bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
                        {lead.source}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-sm font-medium text-foreground">
                      {lead.company || `@${lead.x_handle || "—"}`}
                    </td>
                    <td className="px-5 py-3.5 text-sm text-muted-foreground">{lead.role || "—"}</td>
                    <td className="px-5 py-3.5 text-xs font-mono">
                      {lead.contact_email ? (
                        <span className="inline-flex items-center gap-1.5 text-emerald-600 font-medium">
                          <Mail className="h-3 w-3" />
                          {lead.contact_email}
                        </span>
                      ) : (
                        <span className="text-muted-foreground/60">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="inline-flex items-center gap-1.5">
                        <span className={`h-1.5 w-1.5 rounded-full ${statusDot[lead.status] || "bg-slate-400"}`} />
                        <Badge variant={statusVariantMap[lead.status] || "new"}>
                          {statusLabel(lead.status)}
                        </Badge>
                        {(lead.channel || []).filter((ch) => ch !== "apply").map((ch) => (
                          <Badge key={ch} variant="outline" className="text-[10px] capitalize">
                            {ch}
                          </Badge>
                        ))}
                        {lead.failure_reason && (
                          <Badge variant="rejected" className="text-[10px]">
                            {failureLabel(lead.failure_reason)}
                          </Badge>
                        )}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-sm text-muted-foreground">{lead.posted_date || "—"}</td>
                    <td className="px-5 py-3.5">
                      <ChevronRight className="h-4 w-4 text-muted-foreground/40 transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
                    </td>
                  </motion.tr>
                ))}
              </AnimatePresence>
            </motion.tbody>
          </table>

          {filteredLeads.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16">
              <FileText className="h-8 w-8 text-muted-foreground/40" />
              <p className="mt-3 text-sm text-muted-foreground">No leads in this category</p>
            </div>
          )}
        </div>
      )}

      {/* Detail Sheet */}
      <Sheet open={!!selectedLead} onOpenChange={(open) => !open && setSelectedLead(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
          {selectedLead && (
            <>
              <SheetHeader>
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${statusDot[selectedLead.status] || "bg-slate-400"}`} />
                  <Badge variant={statusVariantMap[selectedLead.status] || "new"}>
                    {statusLabel(selectedLead.status)}
                  </Badge>
                  {(selectedLead.channel || []).filter((ch) => ch !== "apply").map((ch) => (
                    <Badge key={ch} variant="outline" className="text-[10px] capitalize">
                      {ch}
                    </Badge>
                  ))}
                </div>
                <SheetTitle className="font-display text-2xl">
                  {selectedLead.company || `@${selectedLead.x_handle}`}
                </SheetTitle>
                <SheetDescription>
                  {selectedLead.role || "X Lead"} · sourced from {selectedLead.source}
                </SheetDescription>
              </SheetHeader>

              <Tabs defaultValue={selectedLead.id === deepLinkLeadId ? "research" : "overview"} className="mt-6">
                <TabsList className="w-full">
                  <TabsTrigger value="overview" className="flex-1">Overview</TabsTrigger>
                  <TabsTrigger value="jd" className="flex-1">Job</TabsTrigger>
                  <TabsTrigger value="outreach" className="flex-1">Outreach</TabsTrigger>
                  <TabsTrigger value="research" className="flex-1">
                    <Sparkles className="mr-1 h-3 w-3" />
                    Research
                  </TabsTrigger>
                </TabsList>

                {/* Overview */}
                <TabsContent value="overview" className="mt-4 space-y-4">
                  {selectedLead.failure_reason && (
                    <div className="flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 p-4">
                      <div>
                        <p className="text-xs font-medium text-red-700">Needs attention</p>
                        <p className="mt-0.5 text-sm text-red-700">{failureLabel(selectedLead.failure_reason)}</p>
                      </div>
                      <Button size="sm" variant="outline" disabled={actionBusy} onClick={() => doRetry(selectedLead)}>
                        {actionBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Retry"}
                      </Button>
                    </div>
                  )}

                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="rounded-xl border bg-card p-3.5">
                      <p className="text-xs font-medium text-muted-foreground">Contact Email ID</p>
                      <p className="mt-1 font-mono text-xs font-medium text-emerald-600 flex items-center gap-1.5 truncate">
                        <Mail className="h-3.5 w-3.5 flex-shrink-0" />
                        {selectedLead.contact_email || "Not found yet"}
                      </p>
                    </div>
                    <div className="rounded-xl border bg-card p-3.5">
                      <p className="text-xs font-medium text-muted-foreground">Designation / Role</p>
                      <p className="mt-1 text-xs font-medium text-foreground truncate">
                        {selectedLead.role || "—"}
                      </p>
                    </div>
                  </div>

                  {selectedLead.contact_name && (
                    <div className="rounded-xl border bg-card p-3.5">
                      <p className="text-xs font-medium text-muted-foreground">Contact Person</p>
                      <p className="mt-1 text-xs font-medium text-foreground flex items-center gap-1.5">
                        <User className="h-3.5 w-3.5 text-muted-foreground" />
                        {selectedLead.contact_name}
                      </p>
                    </div>
                  )}

                  {selectedLead.resume_version && (
                    <div className="rounded-xl border bg-card p-4">
                      <p className="text-xs font-medium text-muted-foreground">Tailored Resume</p>
                      <p className="mt-1 font-mono text-sm text-foreground">
                        {selectedLead.resume_version}.pdf
                      </p>
                    </div>
                  )}
                  <div className="rounded-xl border bg-card p-4">
                    <p className="text-xs font-medium text-muted-foreground">Posted</p>
                    <p className="mt-1 text-sm text-foreground">{selectedLead.posted_date || "—"}</p>
                  </div>
                  <Separator />
                  <div className="flex gap-2">
                    <Button size="sm" className="flex-1" disabled={actionBusy} onClick={() => doAction("approve", selectedLead)}>
                      {actionBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Approve"}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="flex-1"
                      onClick={() => {
                        setEditing(true);
                        setEditDraft(selectedLead.outreach_draft || "");
                      }}
                    >
                      Edit
                    </Button>
                    <Button size="sm" variant="destructive" className="flex-1" disabled={actionBusy} onClick={() => doAction("reject", selectedLead)}>
                      Reject
                    </Button>
                  </div>
                </TabsContent>

                {/* Job Description */}
                <TabsContent value="jd" className="mt-4">
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-muted-foreground">
                      {stripHtmlToText(selectedLead.jd_text) || "No job description available."}
                    </p>
                  </div>
                </TabsContent>

                {/* Outreach */}
                <TabsContent value="outreach" className="mt-4">
                  <div className="mb-4 space-y-2 rounded-xl border bg-card p-3.5 text-xs shadow-sm">
                    <div className="flex items-start gap-2.5 min-w-0">
                      <div className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40">
                        <Mail className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Recipient Email</p>
                        <p className="mt-0.5 font-mono text-xs font-medium text-emerald-600 dark:text-emerald-400 break-all">
                          {selectedLead.contact_email ? (
                            selectedLead.contact_name ? `${selectedLead.contact_name} <${selectedLead.contact_email}>` : selectedLead.contact_email
                          ) : (
                            <span className="font-sans italic text-muted-foreground">No email address found</span>
                          )}
                        </p>
                      </div>
                    </div>

                    <Separator className="bg-border/60" />

                    <div className="flex items-start gap-2.5 min-w-0">
                      <div className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                        <Briefcase className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Target Designation</p>
                        <p className="mt-0.5 text-xs font-medium text-foreground leading-snug break-words">
                          {selectedLead.role || "—"}
                        </p>
                      </div>
                    </div>
                  </div>

                  {editing ? (
                    <div className="space-y-3">
                      <Textarea
                        value={editDraft}
                        onChange={(e) => setEditDraft(e.target.value)}
                        className="min-h-[200px] text-sm"
                        placeholder="Write the outreach message…"
                      />
                      <div className="flex gap-2">
                        <Button size="sm" disabled={actionBusy} onClick={() => doAction("edit", selectedLead)}>
                          {actionBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save & Approve"}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : selectedLead.outreach_draft ? (
                    <div className="space-y-3">
                      <div className="rounded-xl border bg-card p-4">
                        <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                          {selectedLead.outreach_draft}
                        </p>
                      </div>
                      <Button size="sm" variant="outline" onClick={() => { setEditing(true); setEditDraft(selectedLead.outreach_draft || ""); }}>
                        Edit draft
                      </Button>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-12 text-center">
                      <FileText className="h-7 w-7 text-muted-foreground/40" />
                      <p className="mt-2 text-sm text-muted-foreground">No outreach drafted yet</p>
                    </div>
                  )}
                </TabsContent>

                {/* Research */}
                <TabsContent value="research" className="mt-4">
                  <ResearchPanel lead={selectedLead} />
                </TabsContent>
              </Tabs>
            </>
          )}
        </SheetContent>
      </Sheet>

      <RunPipelineDialog open={scrapeOpen} onOpenChange={setScrapeOpen} />
    </PageTransition>
  );
}
