"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ChevronRight, Sparkles, Workflow } from "lucide-react";
import { MarketingNav } from "@/components/marketing/marketing-nav";
import { PillBadge } from "@/components/marketing/pill-badge";
import { LogoCloud } from "@/components/marketing/logo-cloud";
import { FeatureCards } from "@/components/marketing/feature-cards";
import { HeroPreview } from "@/components/marketing/hero-preview";
import { Footer } from "@/components/marketing/footer";

export default function LandingPage() {
  return (
    <div className="relative min-h-screen">
      <MarketingNav />

      {/* Vertical grid guide lines (crosshair aesthetic) */}
      <div className="pointer-events-none absolute inset-0 z-0 mx-auto hidden max-w-6xl lg:block">
        <div className="absolute left-0 top-0 h-full w-px bg-border/50" />
        <div className="absolute right-0 top-0 h-full w-px bg-border/50" />
      </div>

      <main className="relative z-10">
        {/* === HERO === */}
        <section className="mx-auto max-w-6xl px-6 pt-16 pb-20 md:pt-24">
          <div className="grid items-center gap-12 lg:grid-cols-2">
            {/* Left: copy */}
            <div>
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
              >
                <PillBadge icon={<Sparkles className="h-3 w-3" />}>
                  Fully autonomous outreach
                </PillBadge>
              </motion.div>

              <motion.h1
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.05 }}
                className="mt-6 font-display text-5xl leading-[1.05] text-foreground md:text-6xl"
              >
                The better way to land your next role
              </motion.h1>

              <motion.p
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.12 }}
                className="mt-5 max-w-md text-lg leading-relaxed text-muted-foreground"
              >
                A multi-agent pipeline that sources leads, tailors your resume,
                and drafts outreach — you just approve and send.
              </motion.p>

              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.18 }}
                className="mt-8 flex flex-wrap items-center gap-3"
              >
                <Link
                  href="/dashboard"
                  className="inline-flex items-center gap-1.5 rounded-[10px] bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground shadow-button-brand transition-all hover:shadow-button-brand-hover active:shadow-button-brand-active"
                >
                  Get started
                  <ChevronRight className="h-4 w-4" />
                </Link>
                <Link
                  href="#features"
                  className="inline-flex items-center gap-1.5 rounded-[10px] border border-input bg-card px-5 py-2.5 text-sm font-medium text-foreground shadow-[0px_2px_3px_0px_rgba(0,0,0,0.03)] transition-colors hover:bg-accent"
                >
                  See how it works
                  <ChevronRight className="h-4 w-4" />
                </Link>
              </motion.div>

              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.6, delay: 0.3 }}
                className="mt-4 text-xs text-muted-foreground"
              >
                No spray-and-pray. Every message is reviewed by you.
              </motion.p>
            </div>

            {/* Right: product preview */}
            <div className="lg:pl-8">
              <HeroPreview />
            </div>
          </div>
        </section>

        {/* === LOGO CLOUD === */}
        <section className="border-y border-border/60 bg-card/40 py-10">
          <LogoCloud />
        </section>

        {/* === FEATURES === */}
        <section id="features" className="py-20 md:py-28">
          <div className="mx-auto mb-14 max-w-2xl px-6 text-center">
            <PillBadge icon={<Workflow className="h-3 w-3" />}>
              How it works
            </PillBadge>
            <h2 className="mt-6 font-display text-4xl leading-tight text-foreground md:text-5xl">
              Landing interviews is easy
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              An end-to-end pipeline for individuals who want quality outreach
              at scale, without the busywork.
            </p>
          </div>

          <FeatureCards />

          <div className="mt-14 flex justify-center">
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-1.5 rounded-[10px] bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground shadow-button-brand transition-all hover:shadow-button-brand-hover"
            >
              Open the dashboard
              <ChevronRight className="h-4 w-4" />
            </Link>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}
