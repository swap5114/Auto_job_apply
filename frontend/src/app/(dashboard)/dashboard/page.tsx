"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  ArrowUpRight,
  ArrowDownRight,
  Play,
  Sparkles,
  Briefcase,
  Globe,
  Twitter,
  Building2,
  Send,
  MailOpen,
  FileText,
  Clock,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Button } from "@/components/ui/button";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import { Sparkline } from "@/components/ui/sparkline";
import { AreaChart, type AreaPoint } from "@/components/ui/area-chart";
import { DonutChart } from "@/components/ui/donut-chart";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { staggerContainer, fadeInUp, scaleIn, slideInLeft } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

const activityData: Record<string, AreaPoint[]> = {
  "7d": [
    { label: "Mon", sent: 1, replied: 0 },
    { label: "Tue", sent: 2, replied: 1 },
    { label: "Wed", sent: 2, replied: 0 },
    { label: "Thu", sent: 4, replied: 1 },
    { label: "Fri", sent: 3, replied: 1 },
    { label: "Sat", sent: 5, replied: 2 },
    { label: "Sun", sent: 6, replied: 2 },
  ],
  "30d": [
    { label: "Jul 15", sent: 1, replied: 0 },
    { label: "Jul 18", sent: 3, replied: 1 },
    { label: "Jul 21", sent: 2, replied: 1 },
    { label: "Jul 24", sent: 5, replied: 1 },
    { label: "Jul 27", sent: 4, replied: 2 },
    { label: "Jul 30", sent: 7, replied: 2 },
    { label: "Aug 2", sent: 6, replied: 3 },
    { label: "Aug 5", sent: 9, replied: 3 },
    { label: "Aug 8", sent: 8, replied: 4 },
    { label: "Aug 11", sent: 11, replied: 4 },
    { label: "Aug 14", sent: 12, replied: 5 },
  ],
  "90d": [
    { label: "May", sent: 4, replied: 1 },
    { label: "Jun", sent: 14, replied: 4 },
    { label: "Jul", sent: 28, replied: 9 },
    { label: "Aug", sent: 41, replied: 14 },
  ],
};

const kpis = [
  { label: "New Leads", value: 12, trend: 24, up: true, icon: FileText, spark: [4, 6, 5, 8, 7, 10, 12] },
  { label: "Pending Review", value: 5, trend: 8, up: true, icon: Clock, spark: [2, 3, 2, 4, 3, 5, 5] },
  { label: "Sent", value: 8, trend: 12, up: true, icon: Send, spark: [1, 2, 3, 4, 5, 7, 8] },
  { label: "Reply Rate", value: 25, trend: 5, up: false, icon: MailOpen, spark: [30, 28, 26, 24, 25, 24, 25], suffix: "%" },
];

const funnel = [
  { stage: "Scraped", count: 48, pct: 100 },
  { stage: "Filtered", count: 31, pct: 65 },
  { stage: "Tailored", count: 24, pct: 50 },
  { stage: "Drafted", count: 18, pct: 38 },
  { stage: "Sent", count: 8, pct: 17 },
  { stage: "Replied", count: 2, pct: 4 },
];

const sources = [
  { name: "Arbeitnow", count: 18, icon: Briefcase },
  { name: "Jobicy", count: 14, icon: Globe },
  { name: "Company List", count: 11, icon: Building2 },
  { name: "X / Twitter", count: 5, icon: Twitter },
];
const maxSource = Math.max(...sources.map((s) => s.count));

const recentActivity = [
  { text: "4 new leads scraped from Arbeitnow", meta: "Arbeitnow", time: "2m", tone: "bg-blue-500" },
  { text: "Resume tailored for Migma AI", meta: "Backend Engineer", time: "15m", tone: "bg-violet-500" },
  { text: "Outreach draft generated for TechFlow", meta: "Full Stack Dev", time: "32m", tone: "bg-amber-500" },
  { text: "Email sent to Strix Group", meta: "Software Engineer", time: "2h", tone: "bg-emerald-500" },
  { text: "DataVault replied to your outreach", meta: "Python Developer", time: "5h", tone: "bg-fuchsia-500" },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Panel({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={`rounded-2xl border border-border/70 bg-card shadow-card ${className}`}>
      {children}
    </div>
  );
}

function KpiCard({ kpi }: { kpi: (typeof kpis)[number] }) {
  const TrendIcon = kpi.up ? ArrowUpRight : ArrowDownRight;
  return (
    <motion.div variants={scaleIn}>
      <div className="group relative overflow-hidden rounded-2xl border border-border/70 bg-card p-5 shadow-card transition-shadow duration-300 hover:shadow-card-hover">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-muted-foreground">
            <kpi.icon className="h-3.5 w-3.5" />
            <span className="text-xs font-medium">{kpi.label}</span>
          </div>
          <span
            className={`inline-flex items-center gap-0.5 text-[11px] font-semibold tabular-nums ${kpi.up ? "text-emerald-600" : "text-red-500"
              }`}
          >
            <TrendIcon className="h-3 w-3" />
            {kpi.trend}%
          </span>
        </div>

        <div className="mt-4 flex items-end justify-between">
          <AnimatedCounter
            value={kpi.value}
            suffix={kpi.suffix ?? ""}
            className="font-display text-[2rem] leading-none tabular-nums text-foreground"
          />
          <Sparkline data={kpi.spark} color="hsl(var(--accent-1))" width={72} height={30} />
        </div>
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const [range, setRange] = useState<"7d" | "30d" | "90d">("30d");
  const data = activityData[range];
  const totalSent = data.reduce((s, d) => s + d.sent, 0);
  const totalReplied = data.reduce((s, d) => s + d.replied, 0);

  return (
    <PageTransition>
      <Header
        title="Dashboard"
        description="Your outreach pipeline at a glance"
        action={
          <Button size="sm">
            <Play className="mr-2 h-3.5 w-3.5" />
            Run Pipeline
          </Button>
        }
      />

      <div className="space-y-4 pb-16">
        {/* HERO — Outreach activity chart */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show">
          <Panel className="overflow-hidden">
            <div className="flex flex-wrap items-start justify-between gap-4 p-6 pb-2">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-foreground">Outreach Activity</h3>
                  <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-600">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    Live
                  </span>
                </div>
                <div className="mt-3 flex items-end gap-3">
                  <span className="font-display text-4xl leading-none tabular-nums text-foreground">
                    <AnimatedCounter value={totalSent} />
                  </span>
                  <span className="mb-1 inline-flex items-center gap-0.5 text-xs font-semibold text-emerald-600">
                    <ArrowUpRight className="h-3.5 w-3.5" />
                    18%
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  messages sent · {totalReplied} replies
                </p>
              </div>

              <div className="flex flex-col items-end gap-3">
                <SegmentedControl
                  value={range}
                  onChange={setRange}
                  options={[
                    { label: "7D", value: "7d" },
                    { label: "30D", value: "30d" },
                    { label: "90D", value: "90d" },
                  ]}
                />
                <div className="flex items-center gap-4">
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className="h-2 w-2 rounded-full bg-accent1" />
                    Sent
                  </span>
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className="h-0.5 w-3 rounded-full bg-muted-foreground" />
                    Replied
                  </span>
                </div>
              </div>
            </div>

            <div className="px-3 pb-3">
              <AreaChart key={range} data={data} height={260} />
            </div>
          </Panel>
        </motion.div>

        {/* KPI ROW */}
        <motion.div
          className="grid grid-cols-2 gap-4 lg:grid-cols-4"
          variants={staggerContainer(0.07)}
          initial="hidden"
          animate="show"
        >
          {kpis.map((kpi) => (
            <KpiCard key={kpi.label} kpi={kpi} />
          ))}
        </motion.div>

        {/* FUNNEL + DONUT */}
        <div className="grid gap-4 lg:grid-cols-3">
          <motion.div className="lg:col-span-2" variants={fadeInUp} initial="hidden" animate="show">
            <Panel className="h-full p-6">
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-foreground">Pipeline Funnel</h3>
                  <p className="text-xs text-muted-foreground">Conversion across every stage</p>
                </div>
                <span className="rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium tabular-nums text-muted-foreground">
                  48 total
                </span>
              </div>
              <div className="space-y-2.5">
                {funnel.map((item, i) => (
                  <div key={item.stage} className="flex items-center gap-3">
                    <div className="w-16 shrink-0 text-right text-xs font-medium text-muted-foreground">
                      {item.stage}
                    </div>
                    <div className="relative h-8 flex-1 overflow-hidden rounded-lg bg-muted/50">
                      <motion.div
                        className="absolute inset-y-0 left-0 rounded-lg accent-gradient"
                        style={{ opacity: 0.35 + (item.pct / 100) * 0.65 }}
                        initial={{ width: 0 }}
                        animate={{ width: `${item.pct}%` }}
                        transition={{ duration: 0.9, delay: 0.15 + i * 0.08, ease: [0.21, 1.02, 0.73, 1] }}
                      />
                      <div className="absolute inset-0 flex items-center justify-between px-3">
                        <span className="text-xs font-semibold tabular-nums text-foreground">
                          {item.count}
                        </span>
                        <span className="text-[11px] font-medium tabular-nums text-muted-foreground">
                          {item.pct}%
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          </motion.div>

          <motion.div variants={scaleIn} initial="hidden" animate="show">
            <Panel className="flex h-full flex-col p-6">
              <h3 className="text-sm font-semibold text-foreground">Reply Rate</h3>
              <p className="text-xs text-muted-foreground">Replies vs. sent</p>
              <div className="flex flex-1 items-center justify-center py-4">
                <DonutChart
                  segments={[
                    { label: "Replied", value: 2, color: "accent" },
                    { label: "No reply", value: 6, color: "hsl(var(--muted))" },
                  ]}
                  center={
                    <>
                      <span className="font-display text-3xl tabular-nums text-foreground">
                        <AnimatedCounter value={25} suffix="%" />
                      </span>
                      <span className="text-[11px] text-muted-foreground">2 of 8</span>
                    </>
                  }
                />
              </div>
              <div className="flex items-center justify-center gap-4">
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="h-2 w-2 rounded-full bg-accent1" />
                  Replied
                </span>
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="h-2 w-2 rounded-full bg-muted" />
                  Pending
                </span>
              </div>
            </Panel>
          </motion.div>
        </div>

        {/* SOURCES + ACTIVITY */}
        <div className="grid gap-4 lg:grid-cols-3">
          <motion.div variants={fadeInUp} initial="hidden" animate="show">
            <Panel className="h-full p-6">
              <h3 className="mb-5 text-sm font-semibold text-foreground">Leads by Source</h3>
              <div className="space-y-4">
                {sources.map((s, i) => (
                  <div key={s.name} className="flex items-center gap-3">
                    <s.icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="w-24 shrink-0 truncate text-sm text-foreground">{s.name}</span>
                    <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                      <motion.div
                        className="absolute inset-y-0 left-0 rounded-full accent-gradient"
                        initial={{ width: 0 }}
                        animate={{ width: `${(s.count / maxSource) * 100}%` }}
                        transition={{ duration: 0.8, delay: 0.2 + i * 0.1, ease: [0.21, 1.02, 0.73, 1] }}
                      />
                    </div>
                    <span className="w-6 shrink-0 text-right text-sm font-semibold tabular-nums text-foreground">
                      {s.count}
                    </span>
                  </div>
                ))}
              </div>
            </Panel>
          </motion.div>

          <motion.div className="lg:col-span-2" variants={fadeInUp} initial="hidden" animate="show">
            <Panel className="h-full p-6">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-foreground">Recent Activity</h3>
                <button className="text-xs font-medium text-accent1 hover:underline">
                  View all
                </button>
              </div>
              <motion.div
                className="relative space-y-1"
                variants={staggerContainer(0.06, 0.2)}
                initial="hidden"
                animate="show"
              >
                {/* timeline rail */}
                <div className="absolute bottom-3 left-[7px] top-3 w-px bg-border" />
                {recentActivity.map((a, i) => (
                  <motion.div
                    key={i}
                    variants={slideInLeft}
                    className="relative flex items-center gap-4 rounded-lg py-2 pl-6 pr-2 transition-colors hover:bg-muted/40"
                  >
                    <span className={`absolute left-1 h-2.5 w-2.5 rounded-full ${a.tone} ring-4 ring-card`} />
                    <div className="flex-1">
                      <p className="text-sm text-foreground">{a.text}</p>
                      <p className="text-xs text-muted-foreground">{a.meta}</p>
                    </div>
                    <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
                      {a.time}
                    </span>
                  </motion.div>
                ))}
              </motion.div>
            </Panel>
          </motion.div>
        </div>
      </div>
    </PageTransition>
  );
}
