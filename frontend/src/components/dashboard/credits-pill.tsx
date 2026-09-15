"use client";

import Link from "next/link";
import { Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { OutreachQuota } from "@/lib/quota";

/**
 * Compact credits-remaining pill for the dashboard header. Surfaces how many
 * outreach credits the user has left at a glance, tinted amber/red as they
 * approach or hit their cap, and links to settings/upgrade.
 */
export function CreditsPill({ quota }: { quota: OutreachQuota }) {
  const tone = quota.exhausted
    ? "border-red-200 bg-red-50 text-red-700"
    : quota.nearLimit
      ? "border-amber-200 bg-amber-50 text-amber-700"
      : "border-border bg-card text-foreground";

  return (
    <Link
      href="/settings"
      title={`${quota.remaining} of ${quota.limit} credits left · ${quota.planLabel} plan`}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium shadow-card transition-colors hover:shadow-card-hover",
        tone
      )}
    >
      <Zap className={cn("h-3.5 w-3.5", quota.exhausted || quota.nearLimit ? "" : "text-accent1")} />
      <span className="tabular-nums">
        {quota.remaining}
        <span className="text-muted-foreground">/{quota.limit}</span>
      </span>
      <span className="text-muted-foreground">credits</span>
    </Link>
  );
}
