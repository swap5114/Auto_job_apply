"use client";

import { motion } from "framer-motion";
import { Building2, Clock, Send } from "lucide-react";
import { Badge } from "@/components/ui/badge";

/**
 * Hero product preview — a stylized "lead review" card, echoing Cal.com's
 * hero booking-widget preview but showing the job-pipeline review flow.
 */
export function HeroPreview() {
  const queue = [
    { company: "Migma AI", role: "Backend Engineer", status: "review" as const },
    { company: "TechFlow", role: "Full Stack Dev", status: "review" as const },
    { company: "Strix Group", role: "Software Engineer", status: "sent" as const },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 24, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.7, delay: 0.2, ease: [0.21, 1.02, 0.73, 1] }}
      className="rounded-2xl border bg-card p-5 shadow-dropdown"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
            <Send className="h-4 w-4 text-primary-foreground" />
          </div>
          <div>
            <p className="text-sm font-semibold text-foreground">Review Queue</p>
            <p className="text-xs text-muted-foreground">3 leads pending</p>
          </div>
        </div>
        <Badge variant="review">2 new</Badge>
      </div>

      {/* Queue items */}
      <div className="space-y-2 pt-4">
        {queue.map((item, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.4 + i * 0.12 }}
            className="flex items-center justify-between rounded-lg border border-border/60 bg-background px-3 py-2.5"
          >
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-md bg-muted">
                <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
              </div>
              <div>
                <p className="text-xs font-medium text-foreground">{item.company}</p>
                <p className="text-[11px] text-muted-foreground">{item.role}</p>
              </div>
            </div>
            <Badge variant={item.status} className="text-[10px]">
              {item.status === "review" ? "Pending" : "Sent"}
            </Badge>
          </motion.div>
        ))}
      </div>

      {/* Footer stats */}
      <div className="mt-4 flex items-center gap-4 border-t pt-4">
        <div className="flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">Follow-up in 5 days</span>
        </div>
      </div>
    </motion.div>
  );
}
