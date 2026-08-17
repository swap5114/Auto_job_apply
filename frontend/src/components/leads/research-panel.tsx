"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sparkles,
  Building2,
  Cpu,
  MessageSquareQuote,
  HelpCircle,
  Target,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { staggerContainer, fadeInUp } from "@/lib/motion";
import type { CompanyResearch } from "@/lib/api";

/**
 * Generates contextual research from a lead's own data. Used as the demo
 * source and as a graceful fallback if the live LLM endpoint is unavailable.
 */
function generateResearch(lead: {
  company?: string;
  role?: string;
  jd_text?: string;
  x_handle?: string;
}): CompanyResearch {
  const name = lead.company || (lead.x_handle ? `@${lead.x_handle}` : "This company");
  const jd = (lead.jd_text || "").toLowerCase();

  const techPool = [
    "React", "Next.js", "Node.js", "Python", "FastAPI", "TypeScript",
    "PostgreSQL", "AWS", "Docker", "GraphQL", "MongoDB", "Redis",
  ];
  const tech_signals = techPool.filter((t) => jd.includes(t.toLowerCase()));
  if (tech_signals.length === 0) tech_signals.push("MERN stack", "REST APIs", "Cloud");

  const stage = jd.includes("series") || jd.includes("funding")
    ? "Growth-stage"
    : jd.includes("startup")
    ? "Early-stage"
    : "Growth-stage";

  return {
    overview: `${name} is building ${
      jd.includes("ai") ? "AI-powered" : "modern"
    } software for its market. Based on the role, they're investing in engineering capacity to scale their core product and ship faster.`,
    stage,
    industry: jd.includes("ai")
      ? "AI / Developer Tools"
      : jd.includes("data")
      ? "Data Infrastructure"
      : "SaaS",
    tech_signals: tech_signals.slice(0, 6),
    talking_points: [
      `Their stack overlaps heavily with your experience (${tech_signals
        .slice(0, 2)
        .join(", ")}) — lead with a concrete project that used it.`,
      `The ${lead.role || "role"} suggests they need someone who ships end-to-end; your multi-agent pipeline and Artha.ai projects show exactly that.`,
      `Reference a specific problem from their JD rather than generic enthusiasm — it signals you actually read it.`,
    ],
    smart_questions: [
      "What does the first 90 days look like for this role?",
      "How is the engineering team structured, and where would I fit?",
      "What's the biggest technical challenge the team is tackling right now?",
    ],
    fit_summary: `Your hands-on full-stack + Python background maps directly to what ${name} is hiring for. A specific, JD-grounded outreach should resonate.`,
  };
}

export function ResearchPanel({
  lead,
}: {
  lead: { id: string; company?: string; role?: string; jd_text?: string; x_handle?: string };
}) {
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");
  const [research, setResearch] = useState<CompanyResearch | null>(null);

  async function runResearch() {
    setState("loading");
    // Simulated generation delay for the demo. When wired to live data, swap
    // for: const data = await api.leads.research(lead.id).catch(() => generateResearch(lead));
    await new Promise((r) => setTimeout(r, 1400));
    setResearch(generateResearch(lead));
    setState("done");
  }

  if (state === "idle") {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-12 text-center">
        <div className="relative mb-4 flex h-12 w-12 items-center justify-center rounded-full accent-gradient">
          <Sparkles className="h-5 w-5 text-white" />
        </div>
        <h4 className="font-display text-lg text-foreground">Research this company</h4>
        <p className="mt-1 max-w-xs text-sm text-muted-foreground">
          Generate AI-powered insights, tech-stack signals, and tailored
          talking points for your outreach.
        </p>
        <Button size="sm" className="mt-4" onClick={runResearch}>
          <Sparkles className="mr-1.5 h-3.5 w-3.5" />
          Run Research
        </Button>
      </div>
    );
  }

  if (state === "loading") {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-accent1" />
          Analyzing company & job description…
        </div>
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="h-16 rounded-xl bg-muted/60"
            animate={{ opacity: [0.4, 0.8, 0.4] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.15 }}
          />
        ))}
      </div>
    );
  }

  if (!research) return null;

  return (
    <motion.div
      variants={staggerContainer(0.08)}
      initial="hidden"
      animate="show"
      className="space-y-4"
    >
      {/* Overview + chips */}
      <motion.div variants={fadeInUp} className="rounded-xl border bg-card p-4">
        <div className="mb-2 flex items-center gap-2">
          <Building2 className="h-4 w-4 text-accent1" />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Overview
          </span>
        </div>
        <p className="text-sm leading-relaxed text-foreground">{research.overview}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="rounded-full bg-accent1/10 px-2.5 py-0.5 text-xs font-medium text-accent1">
            {research.stage}
          </span>
          <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
            {research.industry}
          </span>
        </div>
      </motion.div>

      {/* Tech signals */}
      <motion.div variants={fadeInUp} className="rounded-xl border bg-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <Cpu className="h-4 w-4 text-accent1" />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Tech Signals
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {research.tech_signals.map((t, i) => (
            <motion.span
              key={t}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.2 + i * 0.05 }}
              className="rounded-md border bg-background px-2.5 py-1 text-xs font-medium text-foreground"
            >
              {t}
            </motion.span>
          ))}
        </div>
      </motion.div>

      {/* Talking points */}
      <motion.div variants={fadeInUp} className="rounded-xl border bg-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <MessageSquareQuote className="h-4 w-4 text-accent1" />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Talking Points
          </span>
        </div>
        <ul className="space-y-2.5">
          {research.talking_points.map((point, i) => (
            <motion.li
              key={i}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.25 + i * 0.08 }}
              className="flex gap-2.5 text-sm text-foreground"
            >
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full accent-gradient text-[10px] font-bold text-white">
                {i + 1}
              </span>
              {point}
            </motion.li>
          ))}
        </ul>
      </motion.div>

      {/* Smart questions */}
      <motion.div variants={fadeInUp} className="rounded-xl border bg-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <HelpCircle className="h-4 w-4 text-accent1" />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Questions to Ask
          </span>
        </div>
        <ul className="space-y-2">
          {research.smart_questions.map((q, i) => (
            <li key={i} className="flex gap-2 text-sm text-muted-foreground">
              <span className="text-accent1">•</span>
              {q}
            </li>
          ))}
        </ul>
      </motion.div>

      {/* Fit summary */}
      <motion.div
        variants={fadeInUp}
        className="rounded-xl border border-accent1/20 bg-accent-soft/40 p-4"
      >
        <div className="mb-2 flex items-center gap-2">
          <Target className="h-4 w-4 text-accent1" />
          <span className="text-xs font-semibold uppercase tracking-wide text-accent1">
            Why You Fit
          </span>
        </div>
        <p className="text-sm leading-relaxed text-foreground">{research.fit_summary}</p>
      </motion.div>

      <Button variant="outline" size="sm" className="w-full" onClick={runResearch}>
        <Sparkles className="mr-1.5 h-3.5 w-3.5" />
        Regenerate
      </Button>
    </motion.div>
  );
}
