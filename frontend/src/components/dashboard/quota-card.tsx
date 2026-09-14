"use client";

import Link from "next/link";
import { Send, TrendingUp } from "lucide-react";
import { Panel } from "@/components/ui/panel";
import { ProgressRing } from "@/components/ui/progress-ring";
import type { OutreachQuota } from "@/lib/quota";

/**
 * Outreach-remaining quota card. Shows the metered resource (outreach left)
 * right where the user acts, with used/limit, a reset period, and a clear
 * next step — following the "show remaining + total near the metered action,
 * explain the reset" quota UX pattern.
 *
 * `used` is a real number (leads sent, from /api/stats); `limit` comes from
 * the plan-limit config until a backend quota endpoint exists.
 */
export function QuotaCard({ quota }: { quota: OutreachQuota }) {
  const ringValue = Math.round(quota.pct * 100);
  const tone = quota.exhausted
    ? "text-destructive"
    : quota.nearLimit
      ? "text-amber-600"
      : "text-foreground";

  return (
    <Panel className="flex h-full flex-col p-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="eyebrow">Outreach left</p>
          <p className="mt-1 text-xs text-muted-foreground">{quota.resetLabel}</p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
          {quota.planLabel} plan
        </span>
      </div>

      <div className="mt-2 flex flex-1 items-center gap-5">
        <ProgressRing
          value={ringValue}
          size={116}
          stroke={11}
          label={
            <span className={`font-display text-3xl tabular-nums ${tone}`}>{quota.remaining}</span>
          }
          sublabel="left"
        />
        <div className="min-w-0 flex-1 space-y-2.5">
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-muted-foreground">Used this month</span>
            <span className="text-sm font-semibold tabular-nums text-foreground">
              {quota.used}
              <span className="text-muted-foreground">/{quota.limit}</span>
            </span>
          </div>

          {quota.exhausted ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs leading-relaxed text-amber-800">
              You&apos;ve used your {quota.limit} outreach messages for this cycle.
            </div>
          ) : quota.nearLimit ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs leading-relaxed text-amber-800">
              Almost out — {quota.remaining} left before {quota.resetLabel.toLowerCase()}.
            </div>
          ) : (
            <p className="text-xs leading-relaxed text-muted-foreground">
              Each approved message that sends counts once. Drafts you haven&apos;t sent
              don&apos;t count.
            </p>
          )}

          {quota.plan === "free" && (
            <Link
              href="/settings"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-accent1 hover:underline"
            >
              {quota.exhausted || quota.nearLimit ? (
                <>
                  <TrendingUp className="h-3.5 w-3.5" />
                  Upgrade for more
                </>
              ) : (
                <>
                  <Send className="h-3.5 w-3.5" />
                  {quota.remaining} messages ready to use
                </>
              )}
            </Link>
          )}
        </div>
      </div>
    </Panel>
  );
}
