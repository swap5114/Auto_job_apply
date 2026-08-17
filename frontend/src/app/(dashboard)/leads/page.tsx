"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { FileText, Search, ChevronRight, Sparkles } from "lucide-react";
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
import { ResearchPanel } from "@/components/leads/research-panel";
import { staggerContainer, slideInLeft } from "@/lib/motion";

const mockLeads = [
  {
    id: "a1b2c3", source: "jobicy", company: "Acme Corp", role: "Frontend Engineer",
    status: "new", posted_date: "2026-08-12", contact_email: "", resume_version: "",
    outreach_draft: "",
    jd_text: "We're looking for a frontend engineer experienced with React, Next.js, and TypeScript to build our customer dashboard and design system.",
  },
  {
    id: "d4e5f6", source: "x", company: "", role: "", x_handle: "hiringdev",
    status: "new", posted_date: "2026-08-11", contact_email: "", resume_version: "",
    outreach_draft: "",
    jd_text: "Bio: Building the future of remote work. Tweet: We're hiring! Looking for a junior full-stack developer who loves shipping fast.",
  },
  {
    id: "g7h8i9", source: "arbeitnow", company: "TechFlow", role: "Full Stack Developer",
    status: "pending_review", posted_date: "2026-08-10", contact_email: "hr@techflow.io",
    resume_version: "swapnil_jain_resume_techflow",
    outreach_draft: "Subject: Re: Full Stack role at TechFlow\n\nHi TechFlow team,\n\nYour real-time data pipeline platform caught my attention — processing streams at scale is exactly what excites me.",
    jd_text: "Full Stack Developer needed for real-time data pipelines. Node.js, React, PostgreSQL, AWS required. Remote-first team.",
  },
  {
    id: "j1k2l3", source: "careers_page", company: "Migma AI", role: "Backend Product Engineer",
    status: "pending_review", posted_date: "2026-08-09", contact_email: "team@migma.ai",
    resume_version: "swapnil_jain_resume_migma",
    outreach_draft: "Subject: Thoughts on your backend eng search\n\nHi Migma team,\n\nYour work on real-time AI inference infrastructure is compelling.",
    jd_text: "Backend Product Engineer — We're building real-time AI inference infrastructure. Python, FastAPI, distributed systems, Docker. Series A funded.",
  },
  {
    id: "m4n5o6", source: "company_list", company: "Strix Group", role: "Software Engineer",
    status: "sent", posted_date: "2026-08-06", contact_email: "careers@strixgroup.com",
    resume_version: "swapnil_jain_resume_strix",
    outreach_draft: "Subject: Software Engineering role at Strix\n\nHi there,\n\nI noticed your team is scaling its platform.",
    jd_text: "Software Engineer for our platform team. Python, Node.js, AWS. Remote-first.",
  },
  {
    id: "p7q8r9", source: "jobicy", company: "DataVault", role: "Python Developer",
    status: "replied", posted_date: "2026-08-04", contact_email: "hiring@datavault.co",
    resume_version: "swapnil_jain_resume_datavault", outreach_draft: "",
    jd_text: "Python Developer for our data engineering team. FastAPI, PostgreSQL, Redis, Docker.",
  },
  {
    id: "s1t2u3", source: "arbeitnow", company: "CloudBridge", role: "Junior Backend Engineer",
    status: "rejected", posted_date: "2026-08-03", contact_email: "", resume_version: "",
    outreach_draft: "",
    jd_text: "Junior Backend Engineer — AWS Lambda, DynamoDB, Node.js.",
  },
];

type Lead = (typeof mockLeads)[number];

const statusVariantMap: Record<string, "new" | "review" | "approved" | "sent" | "replied" | "rejected"> = {
  new: "new", pending_review: "review", in_review: "review", approved: "approved",
  sent: "sent", draft_created: "sent", replied: "replied", rejected: "rejected",
};

const statusDot: Record<string, string> = {
  new: "bg-slate-400", pending_review: "bg-amber-500", approved: "bg-blue-500",
  sent: "bg-emerald-500", replied: "bg-violet-500", rejected: "bg-red-500",
};

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    new: "New", pending_review: "In Review", in_review: "In Review",
    approved: "Approved", sent: "Sent", draft_created: "Draft",
    replied: "Replied", rejected: "Rejected",
  };
  return labels[status] || status;
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
  const [filter, setFilter] = useState("all");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);

  const filteredLeads =
    filter === "all" ? mockLeads : mockLeads.filter((l) => l.status === filter);

  return (
    <PageTransition>
      <Header
        title="Leads"
        description="All sourced job opportunities"
        action={
          <Button variant="outline" size="sm">
            <Search className="mr-2 h-3.5 w-3.5" />
            Scrape New
          </Button>
        }
      />

      {/* Animated pill filters */}
      <div className="mb-5 flex flex-wrap gap-1.5">
        {filters.map((f) => {
          const isActive = filter === f.key;
          const count =
            f.key === "all"
              ? mockLeads.length
              : mockLeads.filter((l) => l.status === f.key).length;
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
                  {count}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-2xl border bg-card shadow-elevation-low">
        <table className="w-full">
          <thead>
            <tr className="border-b bg-muted/40">
              <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Source</th>
              <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Company</th>
              <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Role</th>
              <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Status</th>
              <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Date</th>
              <th className="w-10 px-5 py-3" />
            </tr>
          </thead>
          <motion.tbody
            key={filter}
            variants={staggerContainer(0.04)}
            initial="hidden"
            animate="show"
          >
            <AnimatePresence mode="popLayout">
              {filteredLeads.map((lead) => (
                <motion.tr
                  key={lead.id}
                  variants={slideInLeft}
                  layout
                  exit={{ opacity: 0 }}
                  className="group cursor-pointer border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                  onClick={() => setSelectedLead(lead)}
                >
                  <td className="px-5 py-3.5">
                    <span className="rounded-md bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
                      {lead.source}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-sm font-medium text-foreground">
                    {lead.company || `@${lead.x_handle || "—"}`}
                  </td>
                  <td className="px-5 py-3.5 text-sm text-muted-foreground">
                    {lead.role || "—"}
                  </td>
                  <td className="px-5 py-3.5">
                    <span className="inline-flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 rounded-full ${statusDot[lead.status]}`} />
                      <Badge variant={statusVariantMap[lead.status] || "default"}>
                        {statusLabel(lead.status)}
                      </Badge>
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-sm text-muted-foreground">
                    {lead.posted_date}
                  </td>
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

      {/* Detail Sheet with tabs */}
      <Sheet open={!!selectedLead} onOpenChange={(open) => !open && setSelectedLead(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
          {selectedLead && (
            <>
              <SheetHeader>
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${statusDot[selectedLead.status]}`} />
                  <Badge variant={statusVariantMap[selectedLead.status] || "default"}>
                    {statusLabel(selectedLead.status)}
                  </Badge>
                </div>
                <SheetTitle className="font-display text-2xl">
                  {selectedLead.company || `@${selectedLead.x_handle}`}
                </SheetTitle>
                <SheetDescription>
                  {selectedLead.role || "X Lead"} · sourced from {selectedLead.source}
                </SheetDescription>
              </SheetHeader>

              <Tabs defaultValue="overview" className="mt-6">
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
                  {selectedLead.contact_email && (
                    <div className="rounded-xl border bg-card p-4">
                      <p className="text-xs font-medium text-muted-foreground">Contact</p>
                      <p className="mt-1 text-sm text-foreground">{selectedLead.contact_email}</p>
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
                    <p className="mt-1 text-sm text-foreground">{selectedLead.posted_date}</p>
                  </div>
                  <Separator />
                  <div className="flex gap-2">
                    <Button size="sm" className="flex-1">Approve</Button>
                    <Button size="sm" variant="outline" className="flex-1">Edit</Button>
                    <Button size="sm" variant="destructive" className="flex-1">Reject</Button>
                  </div>
                </TabsContent>

                {/* Job Description */}
                <TabsContent value="jd" className="mt-4">
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                      {selectedLead.jd_text}
                    </p>
                  </div>
                </TabsContent>

                {/* Outreach */}
                <TabsContent value="outreach" className="mt-4">
                  {selectedLead.outreach_draft ? (
                    <div className="rounded-xl border bg-card p-4">
                      <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                        {selectedLead.outreach_draft}
                      </p>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-12 text-center">
                      <FileText className="h-7 w-7 text-muted-foreground/40" />
                      <p className="mt-2 text-sm text-muted-foreground">
                        No outreach drafted yet
                      </p>
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
    </PageTransition>
  );
}
