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
  Rocket,
  Code2,
  Clock,
  ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { staggerContainer, fadeInUp } from "@/lib/motion";
import { api, type CompanyResearch } from "@/lib/api";
import { toast } from "sonner";
import { DemoBuilder } from "@/components/leads/demo-builder";

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

  // Generate a demo project idea based on JD signals
  const demoIdeas = [
    {
      condition: jd.includes("ai") || jd.includes("llm") || jd.includes("ml"),
      title: `AI Feature Demo for ${name}`,
      description: `Build a small AI-powered tool that solves a problem related to ${name}'s product. For example, an intelligent data classifier, a smart search feature, or an automated content generator.`,
      tech: ["Python", "FastAPI", "Google Gemini API", "React"],
      deliverable: "Live demo link + GitHub repo",
      why: "Shows hands-on AI/ML experience directly relevant to their core product"
    },
    {
      condition: jd.includes("api") || jd.includes("backend"),
      title: `API Integration Demo`,
      description: `Create a mini service that demonstrates clean API design and integration patterns. Include authentication, rate limiting, and comprehensive documentation.`,
      tech: tech_signals.slice(0, 3),
      deliverable: "Live API + Postman collection + GitHub",
      why: "Demonstrates the exact backend skills they're looking for"
    },
    {
      condition: jd.includes("dashboard") || jd.includes("analytics") || jd.includes("data"),
      title: `Analytics Dashboard Prototype`,
      description: `Build a real-time analytics dashboard that visualizes meaningful data. Include interactive charts, filters, and a clean UI that ${name} could imagine in their product.`,
      tech: ["React", "TypeScript", "D3.js", "Node.js"],
      deliverable: "Live demo + video walkthrough",
      why: "Directly showcases frontend + data visualization skills they need"
    },
  ];

  const matchedDemo = demoIdeas.find(d => d.condition) || {
    title: `${lead.role || 'Full-Stack'} Skills Demo`,
    description: `Build a focused tool that showcases your strengths in ${tech_signals.slice(0, 2).join(' and ')}. Make it relevant to ${name}'s domain by solving a real problem their users might face.`,
    tech: tech_signals.slice(0, 4),
    deliverable: "GitHub repo + live demo link",
    why: "Shows initiative and ability to ship working software quickly"
  };

  return {
    overview: `${name} is building ${jd.includes("ai") ? "AI-powered" : "modern"
      } software for its market. Based on the role, they're investing in engineering capacity to scale their core product and ship faster.`,
    stage,
    industry: jd.includes("ai")
      ? "AI / Developer Tools"
      : jd.includes("data")
        ? "Data Infrastructure"
        : "SaaS",
    tech_signals: tech_signals.slice(0, 6),
    demo_project: {
      title: matchedDemo.title,
      description: matchedDemo.description,
      tech_stack: matchedDemo.tech,
      deliverable: matchedDemo.deliverable,
      time_estimate: "2-3 days",
      why_impressive: matchedDemo.why,
    },
    talking_points: [
      `Lead with your demo project — mention you built something specifically for them.`,
      `Their stack overlaps with your experience (${tech_signals.slice(0, 2).join(", ")}) — reference specific projects.`,
      `The ${lead.role || "role"} suggests they need someone who ships end-to-end; your demo proves exactly that.`,
    ],
    smart_questions: [
      "What does the first 90 days look like for this role?",
      "How is the engineering team structured, and where would I fit?",
      "What's the biggest technical challenge the team is tackling right now?",
    ],
    fit_summary: `Your hands-on full-stack background maps directly to what ${name} is hiring for. The demo project will make your outreach stand out from generic applications.`,
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
    try {
      // Real LLM-backed research from the API
      const data = await api.leads.research(lead.id);
      setResearch(data);
    } catch (e: any) {
      // Graceful fallback so the panel still shows something useful
      toast.error(e?.message || "Live research failed — showing a generated draft");
      setResearch(generateResearch(lead));
    } finally {
      setState("done");
    }
  }

  // Rendered unconditionally, ABOVE the idle/loading early returns below.
  // Why: DemoBuilder checks localStorage on mount to recover a build that
  // may already be running for this lead (e.g. started on a previous open
  // of this Sheet). If DemoBuilder only mounted once research reached
  // "done" — as it did before this fix — reopening a lead whose build was
  // started earlier would show the idle "Run Research" prompt with no way
  // to see the still-running build until the user re-ran research (getting
  // a brand-new, unrelated demo idea back from the LLM in the process).
  // Rendering it here means recovery happens the moment the Research tab
  // opens, independent of whether research has been (re-)run in this mount.
  const demoBuilder = <DemoBuilder leadId={lead.id} demoProject={research?.demo_project} />;

  if (state === "idle") {
    return (
      <div className="space-y-4">
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
        {demoBuilder}
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
        {demoBuilder}
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

      {/* Demo Project Idea - THE KEY FEATURE */}
      {research.demo_project && (
        <motion.div
          variants={fadeInUp}
          className="rounded-xl border-2 border-accent1/30 bg-gradient-to-br from-accent1/5 to-accent1/10 p-4"
        >
          <div className="mb-3 flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-full accent-gradient">
              <Rocket className="h-3.5 w-3.5 text-white" />
            </div>
            <span className="text-xs font-semibold uppercase tracking-wide text-accent1">
              Demo Project Idea
            </span>
            <span className="ml-auto rounded-full bg-accent1/20 px-2 py-0.5 text-[10px] font-bold text-accent1">
              KEY DIFFERENTIATOR
            </span>
          </div>

          <h3 className="text-base font-semibold text-foreground mb-2">
            {research.demo_project.title}
          </h3>

          <p className="text-sm text-muted-foreground leading-relaxed mb-3">
            {research.demo_project.description}
          </p>

          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <Code2 className="h-3.5 w-3.5 text-accent1" />
              <span className="text-muted-foreground">Tech:</span>
              <span className="text-foreground font-medium">
                {research.demo_project.tech_stack.join(", ")}
              </span>
            </div>

            <div className="flex items-center gap-2 text-sm">
              <ExternalLink className="h-3.5 w-3.5 text-accent1" />
              <span className="text-muted-foreground">Deliverable:</span>
              <span className="text-foreground font-medium">
                {research.demo_project.deliverable}
              </span>
            </div>

            <div className="flex items-center gap-2 text-sm">
              <Clock className="h-3.5 w-3.5 text-accent1" />
              <span className="text-muted-foreground">Time:</span>
              <span className="text-foreground font-medium">
                {research.demo_project.time_estimate}
              </span>
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-accent1/20">
            <div className="flex items-start gap-2">
              <Sparkles className="h-4 w-4 text-accent1 mt-0.5 shrink-0" />
              <p className="text-sm text-accent1 font-medium">
                {research.demo_project.why_impressive}
              </p>
            </div>
          </div>

          {demoBuilder}
        </motion.div>
      )}

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
