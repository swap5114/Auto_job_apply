"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { CheckCircle2, Circle, Clock, Mail, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Reveal } from "@/components/marketing/reveal";
import { useAuth } from "@/lib/auth-context";

/**
 * Full-bleed dark section (Plane-style) — a near-black band that breaks up the
 * light page. Headline + CTAs, a light product mockup floating on the dark
 * canvas, then a three-column explainer beneath it. Everything reveals on
 * scroll.
 */

const COLUMNS = [
  {
    title: "Reads the whole role, not just the title",
    body: "Every match is scored against your actual resume — target roles, tech stack, seniority, and location — with an explanation for why it fits.",
  },
  {
    title: "Tailors and drafts, you stay in control",
    body: "A tailored resume and a personalized outreach draft are prepared for each company. Nothing is fabricated, and nothing is sent without your approval.",
  },
  {
    title: "Sends from the inbox you already use",
    body: "Approved outreach goes out from your own Gmail — or saves as a draft — so replies land back with you, not in some tool you'll forget to check.",
  },
];

const QUEUE = [
  { company: "Northwind", role: "Backend Engineer", status: "Sent", icon: CheckCircle2, tone: "text-emerald-400" },
  { company: "Atlas", role: "Full-Stack Engineer", status: "Draft ready", icon: Mail, tone: "text-brand" },
  { company: "Meridian", role: "Software Engineer", status: "In review", icon: Clock, tone: "text-white/60" },
  { company: "Kestrel", role: "Platform Engineer", status: "New lead", icon: Circle, tone: "text-white/40" },
];

export function DarkShowcase() {
  const { user } = useAuth();
  const primaryHref = user ? "/dashboard" : "/signin";

  return (
    <section className="w-full bg-[#0a0a0b] py-20 text-white md:py-28">
      <div className="mx-auto max-w-6xl px-6">
        {/* Heading */}
        <Reveal>
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-brand">
            Built around one idea
          </p>
        </Reveal>
        <Reveal delay={0.05}>
          <h2 className="mt-3 max-w-2xl font-display-tight text-4xl text-white md:text-5xl">
            Quality outreach that reads like you wrote it.
          </h2>
        </Reveal>
        <Reveal delay={0.1}>
          <p className="mt-4 max-w-xl text-sm leading-relaxed text-white/60">
            Outra was built for people who want personalized outreach at scale without the
            busywork — and without ever losing the final say.
          </p>
        </Reveal>
        <Reveal delay={0.15}>
          <div className="mt-7 flex flex-wrap gap-3">
            <Button asChild size="lg">
              <Link href={primaryHref}>Get started</Link>
            </Button>
            <Button
              asChild
              size="lg"
              variant="outline"
              className="border-white/20 bg-transparent text-white hover:bg-white/10 hover:text-white"
            >
              <Link href="#faq">Read the FAQ</Link>
            </Button>
          </div>
        </Reveal>

        {/* Floating light mockup */}
        <Reveal delay={0.1} className="mt-14">
          <motion.div className="overflow-hidden rounded-2xl border border-white/10 bg-card text-foreground shadow-[0px_40px_120px_-30px_rgba(0,0,0,0.6)]">
            <div className="flex items-center justify-between border-b border-border/60 px-4 py-3">
              <div className="flex items-center gap-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary text-[10px] font-bold text-primary-foreground">
                  O
                </div>
                <span className="text-sm font-semibold text-foreground">Review Queue</span>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-medium text-brand">
                <Sparkles className="h-3 w-3" /> 4 ready for you
              </span>
            </div>
            <div className="divide-y divide-border/50">
              {QUEUE.map((row, i) => (
                <motion.div
                  key={row.company}
                  initial={{ opacity: 0, x: -12 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, amount: 0.6 }}
                  transition={{ delay: 0.15 + i * 0.08, duration: 0.4 }}
                  className="flex items-center gap-3 px-4 py-3"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-xs font-semibold text-muted-foreground">
                    {row.company.charAt(0)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-foreground">{row.company}</p>
                    <p className="truncate text-xs text-muted-foreground">{row.role}</p>
                  </div>
                  <span className="hidden text-xs text-muted-foreground sm:block">Outreach</span>
                  <span className="inline-flex w-24 shrink-0 items-center justify-end gap-1.5 text-xs">
                    <row.icon className={`h-3.5 w-3.5 ${row.tone === "text-brand" ? "text-brand" : row.tone.includes("emerald") ? "text-emerald-500" : "text-muted-foreground"}`} />
                    <span className="text-foreground/80">{row.status}</span>
                  </span>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </Reveal>

        {/* Three-column explainer */}
        <div className="mt-14 grid gap-8 border-t border-white/10 pt-10 md:grid-cols-3">
          {COLUMNS.map((col, i) => (
            <Reveal key={col.title} delay={i * 0.1}>
              <h3 className="text-sm font-semibold text-white">{col.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/55">{col.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
