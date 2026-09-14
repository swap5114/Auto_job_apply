"use client";

import { Plus } from "lucide-react";
import { Reveal } from "@/components/marketing/reveal";

const FAQS = [
  {
    q: "How does Outra find jobs?",
    a: "Outra scans Y Combinator companies that are actively hiring, pulls their open roles into one queue, and matches each against your resume and preferences — target roles, tech stack, seniority, remote preference, and location. You only see roles that actually fit. (Support for more sources is on the roadmap.)",
  },
  {
    q: "Does it send emails automatically without me?",
    a: "No. Every tailored resume and outreach message sits in a review queue until you approve it. You choose whether approved messages send directly or are saved as Gmail drafts for you to send.",
  },
  {
    q: "Will recruiters know I used Outra?",
    a: "No. Everything sends from your own inbox in your own voice — tailored resumes and outreach read like you wrote them, because they're built from your real experience.",
  },
  {
    q: "How does resume tailoring work?",
    a: "Outra reads the actual job description, aligns your bullets to the keywords and must-haves recruiters screen for, and shows you every change before anything goes out. Nothing is fabricated — it only reshapes what's already true.",
  },
  {
    q: "Will it make up things about me or the company?",
    a: "No. Resume tailoring follows a strict zero-fabrication rule — nothing is claimed that isn't in your real resume. Ideas offered to a company are framed as proposals to start a conversation, never as work you've already done.",
  },
  {
    q: "Why does Outra ask to connect my email?",
    a: "So approved outreach sends from your inbox and replies come straight back to you. Your Gmail connection is stored as an encrypted token and used only to send the messages you approve.",
  },
  {
    q: "Who's behind Outra?",
    a: "A solo developer building in the open. Outra is new — you'd be one of the first people to use it, and feedback goes straight to the person writing the code.",
  },
];

export function FAQ() {
  return (
    <section id="faq" className="mx-auto max-w-6xl px-6 py-20 md:py-28">
      <div className="grid gap-10 lg:grid-cols-[0.8fr_1.4fr] lg:gap-16">
        {/* Left title */}
        <div className="lg:sticky lg:top-24 lg:self-start">
          <p className="eyebrow">Frequently asked</p>
          <h2 className="mt-3 font-display-tight text-4xl text-foreground md:text-5xl">
            What people ask before signing up.
          </h2>
          <p className="mt-5 text-sm leading-relaxed text-muted-foreground">
            Have something else on your mind? Reach out and the developer behind Outra will
            reply personally.
          </p>
        </div>

        {/* Right accordion */}
        <div className="border-t border-border">
          {FAQS.map((item, i) => (
            <Reveal key={item.q} delay={i * 0.04} amount={0.4}>
              <details className="group border-b border-border py-5 [&_summary::-webkit-details-marker]:hidden">
                <summary className="flex cursor-pointer items-center justify-between gap-4 text-[15px] font-medium text-foreground">
                  {item.q}
                  <Plus className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-300 group-open:rotate-45" />
                </summary>
                <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
                  {item.a}
                </p>
              </details>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
