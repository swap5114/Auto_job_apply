"use client";

import { motion } from "framer-motion";
import { Play, Workflow } from "lucide-react";
import { PillBadge } from "@/components/marketing/pill-badge";

const CLIPS = [
  { title: "Upload & match", body: "Attach your resume, tell us who you're targeting, and see matched YC startups in seconds." },
  { title: "Review & edit", body: "Every tailored resume and outreach message waits for your approval — edit anything before it sends." },
  { title: "Send & track", body: "Approved outreach sends from your own Gmail, and replies show up on your dashboard." },
];

export function UsageVideos() {
  return (
    <section id="demo" className="mx-auto max-w-6xl px-6 py-20 md:py-24">
      <div className="mx-auto mb-12 max-w-2xl text-center">
        <PillBadge icon={<Workflow className="h-3 w-3" />}>See it in action</PillBadge>
        <h2 className="mt-6 font-display text-4xl leading-tight text-foreground md:text-5xl">
          Three steps, start to reply
        </h2>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {CLIPS.map((clip, i) => (
          <motion.div
            key={clip.title}
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.4, delay: i * 0.08 }}
          >
            {/* Video placeholder — swap the inner div for an <video>/<iframe>
                once the real walkthrough clips are recorded. */}
            <div className="group relative flex aspect-video items-center justify-center overflow-hidden rounded-xl border border-border/70 bg-muted/40">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-card shadow-card transition-transform group-hover:scale-105">
                <Play className="h-5 w-5 translate-x-0.5 text-accent1" />
              </div>
              <span className="absolute bottom-2 left-2 rounded-md bg-card/80 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                Step {i + 1}
              </span>
            </div>
            <h3 className="mt-3 text-sm font-semibold text-foreground">{clip.title}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{clip.body}</p>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
