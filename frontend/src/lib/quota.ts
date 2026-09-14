import type { Stats } from "@/lib/api";

/**
 * Outreach quota.
 *
 * Credits (lifetime, no reset). The backend is the source of truth: GET
 * /api/outreach/quota returns { plan, used, limit, remaining, reset } where
 * 1 credit = 1 completed-pipeline lead (reached sent/draft_created), used is
 * the lifetime count, and reset is null (credits never reset). Use
 * `quotaFromApi` to shape that response for the UI. `deriveQuota` (from
 * stats) remains only as an offline fallback if the quota request fails.
 */

export type Plan = "free" | "pro" | "power";

/**
 * Offline fallback limits, mirrored from the backend's PLAN_OUTREACH_LIMIT
 * (db/repository.py). Only used if the /api/outreach/quota request fails.
 */
export const PLAN_OUTREACH_LIMIT: Record<Plan, number> = {
  free: 25,
  pro: 250,
  power: 1000,
};

export const PLAN_LABEL: Record<Plan, string> = {
  free: "Free",
  pro: "Pro",
  power: "Power",
};

export interface OutreachQuota {
  plan: Plan;
  planLabel: string;
  used: number;
  limit: number;
  remaining: number;
  /** 0–1 fraction of the allowance consumed. */
  pct: number;
  /** True once the user is within 20% of the cap. */
  nearLimit: boolean;
  /** True when nothing is left. */
  exhausted: boolean;
  /** Human label for when the allowance refreshes. */
  resetLabel: string;
}

function normalizePlan(plan?: string | null): Plan {
  if (plan === "pro" || plan === "power") return plan;
  return "free";
}

/**
 * Label for the credit allowance. Credits are now LIFETIME (no reset), so a
 * null/empty reset from the backend renders as "Lifetime credits" rather
 * than a fake future reset date. A real ISO timestamp (should not happen for
 * lifetime credits) still renders as a reset date for forward-compat.
 */
function resetLabelFrom(iso?: string | null): string {
  if (!iso) return "Lifetime credits";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "Lifetime credits";
  return `Resets ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

/**
 * Build the UI quota object from the real backend response. This is the
 * primary path — the numbers are server-computed and server-enforced.
 */
export function quotaFromApi(res: {
  plan: string;
  used: number;
  limit: number;
  remaining: number;
  reset?: string | null;
}): OutreachQuota {
  const p = normalizePlan(res.plan);
  const limit = res.limit;
  const used = Math.max(0, res.used);
  const remaining = Math.max(0, res.remaining);
  const pct = limit > 0 ? Math.min(1, used / limit) : 0;
  return {
    plan: p,
    planLabel: PLAN_LABEL[p],
    used,
    limit,
    remaining,
    pct,
    nearLimit: remaining > 0 && pct >= 0.8,
    exhausted: remaining <= 0,
    resetLabel: resetLabelFrom(res.reset),
  };
}

/**
 * Derive the outreach quota from real stats + the plan limit config.
 * `used` counts leads already sent (a real number); `sent` is the closest
 * ground-truth the backend exposes today.
 */
export function deriveQuota(stats: Stats | null, plan?: string | null): OutreachQuota {
  const p = normalizePlan(plan);
  const limit = PLAN_OUTREACH_LIMIT[p];
  const used = Math.max(0, stats?.sent ?? 0);
  const remaining = Math.max(0, limit - used);
  const pct = limit > 0 ? Math.min(1, used / limit) : 0;
  return {
    plan: p,
    planLabel: PLAN_LABEL[p],
    used,
    limit,
    remaining,
    pct,
    nearLimit: remaining > 0 && pct >= 0.8,
    exhausted: remaining <= 0,
    resetLabel: "Lifetime credits",
  };
}
