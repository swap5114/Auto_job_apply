"use client";

import { motion } from "framer-motion";
import { Hammer, Twitter, Sparkles } from "lucide-react";
import { PillBadge } from "@/components/marketing/pill-badge";

const UPCOMING = [
  {
    icon: Hammer,
    title: "Demo builder",
    body: "Go beyond proposing an idea — have a working prototype built and deployed for the company, ready to share in your outreach.",
  },
  {
    icon: Twitter,
    title: "X / Twitter sourcing",
    body: "Catch real-time hiring signals from founders posting on X, and reach out while the role is still hot.",
  },
];

export function UpcomingFeatures() {
  return (
    <section id="upcoming" className="mx-auto max-w-6xl px-6 py-20 md:py-24">
      <div className="mx-auto mb-12 max-w-2xl text-center">
        <PillBadge icon={<Sparkles className="h-3 w-3" />}>Coming soon</PillBadge>
        <h2 className="mt-6 font-display text-4xl leading-tight text-foreground md:text-5xl">
          On the roadmap
        </h2>
        <p className="mt-4 text-lg text-muted-foreground">
          What we&apos;re building next. Available today: YC-startup sourcing, tailored resumes,
          and personalized outreach from your own inbox.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {UPCOMING.map((f, i) => (
          <motion.div
            key={f.title}
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.4, delay: i * 0.08 }}
            className="relative overflow-hidden rounded-2xl border border-border/70 bg-card p-6 shadow-card"
          >
            <span className="absolute right-4 top-4 rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
              Upcoming
            </span>
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent1/10">
              <f.icon className="h-5 w-5 text-accent1" />
            </div>
            <h3 className="mt-4 font-display text-lg text-foreground">{f.title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{f.body}</p>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
