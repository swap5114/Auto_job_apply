"use client";

import { motion } from "framer-motion";
import {
  Briefcase,
  Globe,
  FileText,
  Mail,
  Check,
} from "lucide-react";

/**
 * Product mockup previews for the feature cards — job-pipeline flavored
 * versions of Cal.com's calendar-orbit / availability-toggles / meeting
 * cards. Each is a self-contained decorative visual.
 */

// Mockup 1: Sourcing orbit — lead sources circling the pipeline core
export function SourcingOrbitMockup() {
  const sources = [
    { icon: Briefcase, angle: 0, color: "text-blue-600 bg-blue-50" },
    { icon: Globe, angle: 90, color: "text-emerald-600 bg-emerald-50" },
    { icon: FileText, angle: 180, color: "text-violet-600 bg-violet-50" },
    { icon: Mail, angle: 270, color: "text-amber-600 bg-amber-50" },
  ];

  return (
    <div className="relative flex h-44 items-center justify-center">
      {/* Orbit rings */}
      <div className="absolute h-40 w-40 rounded-full border border-dashed border-border" />
      <div className="absolute h-28 w-28 rounded-full border border-dashed border-border" />

      {/* Center */}
      <div className="z-10 flex items-center rounded-full border bg-card px-3 py-1.5 shadow-elevation-low">
        <span className="text-xs font-semibold text-foreground">Outra</span>
      </div>

      {/* Orbiting source icons */}
      {sources.map((s, i) => {
        const rad = (s.angle * Math.PI) / 180;
        const r = 80;
        const x = Math.cos(rad) * r;
        const y = Math.sin(rad) * r;
        return (
          <motion.div
            key={i}
            className={`absolute flex h-8 w-8 items-center justify-center rounded-lg shadow-elevation-low ${s.color}`}
            style={{ left: `calc(50% + ${x}px - 16px)`, top: `calc(50% + ${y}px - 16px)` }}
            animate={{ y: [0, -4, 0] }}
            transition={{ duration: 2.5, repeat: Infinity, delay: i * 0.3 }}
          >
            <s.icon className="h-4 w-4" />
          </motion.div>
        );
      })}
    </div>
  );
}

// Mockup 2: Criteria toggles — like Cal.com's availability rows
export function CriteriaTogglesMockup() {
  const rows = [
    { label: "Remote", on: true },
    { label: "Senior roles", on: false },
    { label: "1+ yr exp", on: true },
  ];

  return (
    <div className="flex h-44 items-center justify-center">
      <div className="w-full max-w-[240px] space-y-2 rounded-xl border bg-card p-3 shadow-elevation-low">
        {rows.map((row, i) => (
          <div
            key={i}
            className="flex items-center justify-between rounded-lg border border-border/60 bg-background px-3 py-2"
          >
            <div className="flex items-center gap-2">
              <div
                className={`flex h-4 w-7 items-center rounded-full p-0.5 transition-colors ${
                  row.on ? "bg-primary" : "bg-muted-foreground/30"
                }`}
              >
                <motion.div
                  className="h-3 w-3 rounded-full bg-white"
                  animate={{ x: row.on ? 12 : 0 }}
                  transition={{ type: "spring", stiffness: 500, damping: 30 }}
                />
              </div>
              <span
                className={`text-xs font-medium ${
                  row.on ? "text-foreground" : "text-muted-foreground"
                }`}
              >
                {row.label}
              </span>
            </div>
            <span className="text-[10px] font-mono text-muted-foreground">
              {row.on ? "include" : "exclude"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Mockup 3: Outreach preview — a drafted email card
export function OutreachMockup() {
  return (
    <div className="flex h-44 items-center justify-center">
      <div className="w-full max-w-[240px] rounded-xl border bg-card shadow-elevation-low">
        <div className="flex items-center gap-2 border-b px-3 py-2">
          <div className="flex gap-1">
            <div className="h-2 w-2 rounded-full bg-red-400" />
            <div className="h-2 w-2 rounded-full bg-amber-400" />
            <div className="h-2 w-2 rounded-full bg-emerald-400" />
          </div>
          <span className="ml-1 text-[10px] text-muted-foreground">Draft</span>
        </div>
        <div className="space-y-2 p-3">
          <div className="h-2 w-3/4 rounded bg-foreground/80" />
          <div className="space-y-1.5 pt-1">
            <div className="h-1.5 w-full rounded bg-muted-foreground/25" />
            <div className="h-1.5 w-full rounded bg-muted-foreground/25" />
            <div className="h-1.5 w-2/3 rounded bg-muted-foreground/25" />
          </div>
          <div className="flex items-center gap-1.5 pt-2">
            <div className="flex h-5 items-center gap-1 rounded-md bg-emerald-600 px-2">
              <Check className="h-2.5 w-2.5 text-white" />
              <span className="text-[9px] font-medium text-white">Approve</span>
            </div>
            <div className="h-5 rounded-md border border-border px-2 text-[9px] font-medium leading-5 text-muted-foreground">
              Edit
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
