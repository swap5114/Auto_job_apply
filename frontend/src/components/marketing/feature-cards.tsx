"use client";

import { motion } from "framer-motion";
import {
  SourcingOrbitMockup,
  CriteriaTogglesMockup,
  OutreachMockup,
} from "./feature-mockups";

const features = [
  {
    number: "01",
    title: "Source from YC startups",
    description:
      "We scan Y Combinator companies that are actively hiring and pull their open roles into one clean queue. More sources are on the roadmap.",
    mockup: SourcingOrbitMockup,
  },
  {
    number: "02",
    title: "Set your criteria",
    description:
      "Want only remote junior roles? Exclude senior titles? Define keywords once and we filter every lead automatically.",
    mockup: CriteriaTogglesMockup,
  },
  {
    number: "03",
    title: "Review, then send",
    description:
      "Every resume is tailored and every outreach drafted. You approve, edit, or reject — nothing sends without you.",
    mockup: OutreachMockup,
  },
];

export function FeatureCards() {
  return (
    <div className="mx-auto grid max-w-6xl gap-4 px-6 md:grid-cols-3">
      {features.map((feature, i) => {
        const Mockup = feature.mockup;
        return (
          <motion.div
            key={feature.number}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.5, delay: i * 0.1, ease: [0.21, 1.02, 0.73, 1] }}
            className="rounded-2xl border bg-card p-6 shadow-elevation-low"
          >
            <div className="mb-4 inline-flex items-center rounded-md bg-muted px-2 py-0.5">
              <span className="font-mono text-xs text-muted-foreground">
                {feature.number}
              </span>
            </div>
            <h3 className="font-display text-xl text-foreground">
              {feature.title}
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              {feature.description}
            </p>
            <div className="mt-6">
              <Mockup />
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
