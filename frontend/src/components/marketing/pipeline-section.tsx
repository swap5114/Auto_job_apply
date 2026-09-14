"use client";

import { useRef, useState } from "react";
import {
  motion,
  AnimatePresence,
  useScroll,
  useMotionValueEvent,
} from "framer-motion";
import { Check } from "lucide-react";

/**
 * The animated 4-stage pipeline — the centerpiece of the landing page. A
 * horizontal stepper (Source -> Tailor -> Draft -> Review & send) with a
 * warm-orange connector that fills as you scroll. The section is a tall
 * scroll track with a sticky inner viewport: scroll progress drives which
 * step is active (Plane-style), and clicking a step scrolls you to it.
 */

const STEPS = [
  {
    key: "source",
    label: "Source",
    blurb:
      "Outra scans Y Combinator companies that are actively hiring, pulls their open roles into one clean queue, and matches each against your resume — so you only see roles that actually fit.",
  },
  {
    key: "tailor",
    label: "Tailor",
    blurb:
      "For each role, your resume is reshaped around the actual job description — the keywords and must-haves recruiters screen for. Every change is shown to you, and nothing is invented that isn't already true.",
  },
  {
    key: "draft",
    label: "Draft",
    blurb:
      "Outra drafts outreach that opens with a genuinely useful idea for the company — not a generic template. Built from your real experience, in your voice.",
  },
  {
    key: "send",
    label: "Review & send",
    blurb:
      "Everything waits in a review queue until you approve, edit, or reject it. Approved messages send from your own Gmail — or save as drafts — so replies come straight back to you.",
  },
] as const;

export function PipelineSection() {
  const [active, setActive] = useState(0);
  const trackRef = useRef<HTMLDivElement>(null);

  // Scroll progress across the tall track. As the sticky panel is pinned, the
  // scroll position maps to which of the 4 steps is active.
  const { scrollYProgress } = useScroll({
    target: trackRef,
    offset: ["start start", "end end"],
  });

  useMotionValueEvent(scrollYProgress, "change", (p) => {
    // Bias slightly so each step "holds" for a comfortable stretch.
    const idx = Math.min(STEPS.length - 1, Math.floor(p * STEPS.length * 0.999));
    setActive((prev) => (prev === idx ? prev : idx));
  });

  const progress = STEPS.length > 1 ? active / (STEPS.length - 1) : 0;

  // Clicking a step scrolls you to the matching slice of the track.
  const goTo = (i: number) => {
    const el = trackRef.current;
    if (!el) return;
    const top = el.offsetTop + (el.offsetHeight - window.innerHeight) * (i / STEPS.length);
    window.scrollTo({ top, behavior: "smooth" });
  };

  return (
    <section id="pipeline" ref={trackRef} className="relative h-[340vh]">
      {/* Sticky viewport — pinned while you scroll the track */}
      <div className="sticky top-0 flex min-h-screen items-center">
        <div className="mx-auto w-full max-w-6xl px-6 py-16">
          {/* Heading */}
          <p className="eyebrow">The pipeline</p>
          <h2 className="mt-3 max-w-xl font-display-tight text-4xl text-foreground md:text-5xl">
            Four steps. One queue. You approve everything.
          </h2>

          {/* Stepper */}
          <div className="mt-8">
            <div className="relative flex items-center justify-between">
              {/* Track line */}
              <div className="absolute left-0 right-0 top-1/2 h-px -translate-y-1/2 bg-border" />
              {/* Filled line */}
              <motion.div
                className="absolute left-0 top-1/2 h-px -translate-y-1/2 bg-brand"
                animate={{ width: `${progress * 100}%` }}
                transition={{ type: "spring", stiffness: 120, damping: 24 }}
              />
              {STEPS.map((step, i) => {
                const isActive = i === active;
                const isDone = i < active;
                return (
                  <button
                    key={step.key}
                    onClick={() => goTo(i)}
                    className={`relative z-10 inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors ${isActive
                      ? "border-transparent bg-primary text-primary-foreground"
                      : isDone
                        ? "border-brand/40 bg-background text-foreground"
                        : "border-border bg-background text-muted-foreground"
                      }`}
                  >
                    <span
                      className={`tabular-nums ${isActive ? "text-primary-foreground/60" : "text-muted-foreground/70"
                        }`}
                    >
                      0{i + 1}
                    </span>
                    <span className="flex items-center gap-1">
                      {isDone && <Check className="h-3 w-3 text-brand" />}
                      {step.label}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Blurb */}
            <AnimatePresence mode="wait">
              <motion.p
                key={STEPS[active].key}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.3 }}
                className="mt-6 max-w-2xl text-sm leading-relaxed text-muted-foreground"
              >
                {STEPS[active].blurb}
              </motion.p>
            </AnimatePresence>
          </div>

          {/* Stage mockups */}
          <div className="mt-8 grid gap-4 lg:grid-cols-2">
            <AnimatePresence mode="wait">
              <motion.div
                key={`left-${STEPS[active].key}`}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.35, ease: [0.21, 1.02, 0.73, 1] }}
              >
                <StageLeft step={active} />
              </motion.div>
            </AnimatePresence>
            <AnimatePresence mode="wait">
              <motion.div
                key={`right-${STEPS[active].key}`}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.35, delay: 0.05, ease: [0.21, 1.02, 0.73, 1] }}
                className="space-y-4"
              >
                <StageRight step={active} />
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------------- */
/* Reusable primitives                                                    */
/* --------------------------------------------------------------------- */

function DarkPanel({
  eyebrow,
  title,
  children,
  className = "",
}: {
  eyebrow: string;
  title: string;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-2xl bg-[#0b0b0d] p-5 text-white ${className}`}>
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-brand">{eyebrow}</p>
      <p className="mt-2 font-display text-lg leading-tight">{title}</p>
      <div className="mt-4">{children}</div>
    </div>
  );
}

function LightCard({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-border/70 bg-card p-5 shadow-card">
      <p className="eyebrow">{eyebrow}</p>
      <p className="mt-1.5 text-sm font-semibold text-foreground">{title}</p>
      <div className="mt-3">{children}</div>
    </div>
  );
}

/* --------------------------------------------------------------------- */
/* Stage content                                                          */
/* --------------------------------------------------------------------- */

function StageLeft({ step }: { step: number }) {
  if (step === 0) {
    // SOURCE — dark terminal pulling + deduping leads into one queue
    return (
      <DarkPanel eyebrow="01 · Source" title="YC companies hiring now, one clean queue." className="h-full">
        <div className="space-y-1.5 font-mono text-[10px] leading-relaxed text-white/50">
          <p>scanning Y Combinator companies…</p>
          <p>
            filtering to <span className="text-white/70">actively hiring</span>
          </p>
          <p>
            collecting open roles →{" "}
            <span className="text-white/70">63</span> found
          </p>
          <p className="pt-2 text-brand">→ 63 roles matched against your resume</p>
        </div>
        <div className="mt-4 space-y-1.5">
          {[
            ["Backend Engineer", "strong fit"],
            ["Full-Stack Engineer", "good fit"],
            ["Platform Engineer", "good fit"],
          ].map(([role, fit]) => (
            <div
              key={role}
              className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px]"
            >
              <span className="text-white/80">{role}</span>
              <span className="font-mono text-[9px] uppercase tracking-wide text-brand">{fit}</span>
            </div>
          ))}
        </div>
      </DarkPanel>
    );
  }
  if (step === 1) {
    // TAILOR — light cards, JD parsing + bullet rewrite (illustrative)
    return (
      <div className="space-y-4">
        <LightCard eyebrow="01 · Reads the job description" title="Keywords and must-haves, pulled out">
          <p className="text-xs leading-relaxed text-muted-foreground">
            Engineer experienced with{" "}
            <mark className="rounded bg-brand-soft px-1 text-brand">Python</mark>,{" "}
            <mark className="rounded bg-brand-soft px-1 text-brand">React</mark>, and{" "}
            <mark className="rounded bg-brand-soft px-1 text-brand">Postgres</mark>, comfortable owning
            features <mark className="rounded bg-brand-soft px-1 text-brand">end to end</mark>.
          </p>
        </LightCard>
        <LightCard eyebrow="02 · Reshapes your real bullets" title="Aligned to the role — never invented">
          <p className="text-xs text-muted-foreground line-through opacity-60">
            Worked on the web app and some backend tasks.
          </p>
          <p className="mt-1.5 text-xs font-medium text-foreground">
            Built full-stack features in React and Python, shipping end to end against Postgres.
          </p>
          <p className="mt-2 font-mono text-[9px] uppercase tracking-wide text-brand">
            Illustrative — drawn from your own resume
          </p>
        </LightCard>
      </div>
    );
  }
  if (step === 2) {
    // DRAFT — light card, outreach opening with a useful idea
    return (
      <LightCard eyebrow="01 · The opening line" title="Starts with a useful idea, not a template">
        <p className="text-xs leading-relaxed text-muted-foreground">
          &ldquo;Noticed your onboarding drops users at the API-key step — here&apos;s a small change
          that could lift activation, and why I&apos;d be a good fit to build it with you.&rdquo;
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {["From your resume", "Specific to them", "No fabrication"].map((t) => (
            <span key={t} className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
              {t}
            </span>
          ))}
        </div>
      </LightCard>
    );
  }
  // SEND — dark review-then-send composer
  return (
    <DarkPanel eyebrow="01 · Nothing sends without you" title="Approve, edit, or reject — your call." className="h-full">
      <div className="space-y-2 text-[11px] leading-relaxed text-white/70">
        <p className="text-white/50">To: hiring@company.com · from your Gmail</p>
        <p>Subject: An idea for your onboarding — and a quick intro</p>
        <p className="text-white/50">Hi team, I&apos;ve been following what you&apos;re building…</p>
      </div>
      <div className="mt-4 flex items-center justify-between">
        <span className="font-mono text-[9px] uppercase tracking-wide text-white/30">
          In review · not sent yet
        </span>
        <div className="flex gap-2">
          <span className="rounded-md border border-white/15 px-3 py-1 text-[10px] text-white/70">Edit</span>
          <span className="rounded-md bg-brand px-3 py-1 text-[10px] font-medium text-white">Approve &amp; send</span>
        </div>
      </div>
    </DarkPanel>
  );
}

function StageRight({ step }: { step: number }) {
  if (step === 0) {
    return (
      <>
        <LightCard eyebrow="02 · Your criteria" title="Set the filters once">
          <div className="flex flex-wrap gap-2">
            {["Backend / Full-stack", "Remote", "Junior–mid", "Exclude senior"].map((c) => (
              <span key={c} className="rounded-full border border-border/60 bg-background px-2.5 py-1 text-[11px] text-muted-foreground">
                {c}
              </span>
            ))}
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
            Define your target roles, keywords, and exclusions — every new lead is filtered
            against them automatically.
          </p>
        </LightCard>
        <LightCard eyebrow="03 · One queue" title="No trawling job boards yourself">
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Matched roles land in a single queue, so you review each company once — instead of
            refreshing YC&apos;s jobs page hoping to catch a new posting before everyone else.
          </p>
        </LightCard>
      </>
    );
  }
  if (step === 1) {
    return (
      <LightCard eyebrow="03 · The zero-fabrication rule" title="It reshapes what's true — it never makes things up">
        <p className="text-xs leading-relaxed text-muted-foreground">
          Tailoring only rephrases and re-emphasizes what&apos;s already in your resume to match the
          role. It won&apos;t add a skill, a title, or a result you didn&apos;t have — and you see
          every change before anything is used.
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {["Every change shown", "Nothing invented", "You have final edit"].map((t) => (
            <span key={t} className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
              {t}
            </span>
          ))}
        </div>
      </LightCard>
    );
  }
  if (step === 2) {
    return (
      <LightCard eyebrow="02 · Why it lands" title="A proposal, never finished work">
        <p className="text-xs leading-relaxed text-muted-foreground">
          Ideas for the company are offered as suggestions to open a conversation — not claims that
          you&apos;ve already built something for them. Genuinely useful, and honest about what it is.
        </p>
      </LightCard>
    );
  }
  return (
    <LightCard eyebrow="02 · From your own inbox" title="Replies come straight back to you">
      <p className="text-xs leading-relaxed text-muted-foreground">
        Connect your Gmail with Google sign-in and approved outreach sends from your address — or
        saves as a draft for you to send. Your connection is stored as an encrypted token, used
        only for the messages you approve.
      </p>
    </LightCard>
  );
}
