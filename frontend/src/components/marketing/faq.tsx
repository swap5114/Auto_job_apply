"use client";

import { ChevronDown, HelpCircle } from "lucide-react";
import { PillBadge } from "@/components/marketing/pill-badge";

const FAQS = [
  {
    q: "Does it send emails automatically without me?",
    a: "No. Every tailored resume and outreach message sits in a review queue until you approve it. You choose whether approved messages send directly or are saved as Gmail drafts for you to send.",
  },
  {
    q: "Whose email address does the outreach come from?",
    a: "Your own. You connect your Gmail with Google sign-in, and approved outreach sends from your inbox — so replies come straight back to you.",
  },
  {
    q: "Where do the startups come from?",
    a: "Y Combinator companies that are actively hiring. You describe who you're targeting, and we match them against your resume.",
  },
  {
    q: "Will it make up things about me or the company?",
    a: "No. Resume tailoring and outreach are held to a strict zero-fabrication rule — nothing is claimed that isn't in your real resume, and ideas for the company are offered as proposals, never as finished work.",
  },
  {
    q: "Is my resume data private?",
    a: "Your resume, criteria, and leads are scoped to your account. Your Gmail connection is stored as an encrypted token and used only to send the outreach you approve.",
  },
];

export function FAQ() {
  return (
    <section id="faq" className="mx-auto max-w-3xl px-6 py-20 md:py-24">
      <div className="mb-10 text-center">
        <PillBadge icon={<HelpCircle className="h-3 w-3" />}>FAQ</PillBadge>
        <h2 className="mt-6 font-display text-4xl leading-tight text-foreground md:text-5xl">
          Questions, answered
        </h2>
      </div>

      <div className="space-y-3">
        {FAQS.map((item) => (
          <details
            key={item.q}
            className="group rounded-xl border border-border/70 bg-card px-5 py-4 shadow-card [&_summary::-webkit-details-marker]:hidden"
          >
            <summary className="flex cursor-pointer items-center justify-between gap-4 text-sm font-medium text-foreground">
              {item.q}
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
            </summary>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{item.a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
