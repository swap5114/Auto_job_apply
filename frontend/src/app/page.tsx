"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { MarketingNav } from "@/components/marketing/marketing-nav";
import { Button } from "@/components/ui/button";
import { HeroDashboard } from "@/components/marketing/hero-dashboard";
import { PipelineSection } from "@/components/marketing/pipeline-section";
import { DarkShowcase } from "@/components/marketing/dark-showcase";
import { FAQ } from "@/components/marketing/faq";
import { FinalCta } from "@/components/marketing/final-cta";
import { Footer } from "@/components/marketing/footer";
import { useAuth } from "@/lib/auth-context";

export default function LandingPage() {
  // Signed-in visitors skip straight to the dashboard; everyone else goes
  // through /signin first.
  const { user } = useAuth();
  const primaryHref = user ? "/dashboard" : "/signin";

  return (
    <div className="relative min-h-screen">
      <MarketingNav />

      {/* Vertical grid guide lines (crosshair aesthetic) — scoped to the
          top light area so they don't run through the dark sections. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-0 mx-auto hidden h-[220vh] max-w-6xl lg:block">
        <div className="absolute left-0 top-0 h-full w-px bg-border/50" />
        <div className="absolute right-0 top-0 h-full w-px bg-border/50" />
      </div>

      <main className="relative z-10">
        {/* === HERO === */}
        <section className="mx-auto max-w-5xl px-6 pt-16 text-center md:pt-24">
          {/* Eyebrow pill — honest positioning, no false claims */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="flex justify-center"
          >
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground shadow-[0px_1px_2px_0px_rgba(0,0,0,0.04)]">
              <Sparkles className="h-3 w-3 text-brand" />
              Personalized outreach, not spray-and-pray
            </span>
          </motion.div>

          {/* Headline */}
          <motion.h1
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.05 }}
            className="mx-auto mt-7 max-w-3xl font-display-tight text-5xl text-foreground sm:text-6xl md:text-[4.25rem]"
          >
            Outreach to startups that actually gets read.
          </motion.h1>

          {/* Subcopy — describes the real flow */}
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.12 }}
            className="mx-auto mt-6 max-w-xl text-[15px] leading-relaxed text-muted-foreground"
          >
            Outra finds Y Combinator startups hiring for roles that fit you, tailors your resume to
            each one, and drafts outreach that opens with a genuinely useful idea for them. You
            review everything, and it sends from your own inbox.
          </motion.p>

          {/* CTAs */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.18 }}
            className="mt-8 flex flex-wrap items-center justify-center gap-3"
          >
            <Button asChild size="lg">
              <Link href={primaryHref}>Get started</Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="#pipeline">See how it works</Link>
            </Button>
          </motion.div>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.26 }}
            className="mt-3 text-xs text-muted-foreground"
          >
            Free to start. No card required. You approve every message.
          </motion.p>

          {/* Product mockup (has its own entrance animation) */}
          <div className="mt-14 pb-4">
            <HeroDashboard />
          </div>
        </section>

        {/* === PIPELINE (scroll-driven 4-step) === */}
        <div className="border-t border-border/60">
          <PipelineSection />
        </div>

        {/* === FULL-WIDTH DARK SHOWCASE === */}
        <DarkShowcase />

        {/* === FAQ === */}
        <section className="border-t border-border/60">
          <FAQ />
        </section>

        {/* === FINAL CTA === */}
        <section className="border-t border-border/60 bg-card/40">
          <FinalCta />
        </section>
      </main>

      <Footer />
    </div>
  );
}
