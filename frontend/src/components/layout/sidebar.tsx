"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  FileText,
  FileEdit,
  Hammer,
  CheckCircle2,
  Settings,
  Sparkles,
  Play,
  Loader2,
  Square,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api, type Stats } from "@/lib/api";
import { usePipelineStatus } from "@/lib/use-pipeline-status";
import { RunPipelineDialog } from "@/components/pipeline/run-pipeline-dialog";
import { useAuth } from "@/lib/auth-context";
import { OutraLogo } from "@/components/ui/outra-logo";

/**
 * Left navigation sidebar — replaces the floating top bar. Matches the
 * reference: brand mark up top, a vertical nav list with icons + badges,
 * pipeline run controls, and a user card pinned to the bottom.
 *
 * Rendered as a fixed-width column by the dashboard layout; the whole shell
 * is a full-width sidebar + content grid.
 */
export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [stats, setStats] = useState<Stats | null>(null);
  const [runOpen, setRunOpen] = useState(false);

  const { state, abort, aborting } = usePipelineStatus();
  const running = state?.running ?? false;

  const { user, signOut } = useAuth();

  // Fetch real counts for nav badges once on mount (stats reads are slow /
  // rate-limited, so no interval polling — refresh only after a run finishes).
  useEffect(() => {
    let active = true;
    api.stats
      .get()
      .then((s) => active && setStats(s))
      .catch(() => { });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!running && state?.finished_at) {
      api.stats.get().then(setStats).catch(() => { });
    }
  }, [running, state?.finished_at]);

  const leadsBadge = stats?.total ?? null;
  const reviewBadge = stats ? (stats.pending_review ?? 0) + (stats.in_review ?? 0) : null;

  const navigation = [
    { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard, badge: null as number | null },
    { name: "Matches", href: "/matches", icon: Sparkles, badge: null as number | null },
    { name: "Resume", href: "/resume", icon: FileEdit, badge: null as number | null },
    { name: "Leads", href: "/leads", icon: FileText, badge: leadsBadge },
    { name: "Review", href: "/review", icon: CheckCircle2, badge: reviewBadge },
    { name: "Builds", href: "/builds", icon: Hammer, badge: null as number | null },
    { name: "Settings", href: "/settings", icon: Settings, badge: null as number | null },
  ];

  async function handleSignOut() {
    await signOut();
    router.replace("/");
  }

  const displayName = user?.displayName || user?.email?.split("@")[0] || "Your account";
  const initial = displayName.charAt(0).toUpperCase();

  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-40 flex w-[248px] flex-col border-r border-border/70 bg-card/80 backdrop-blur-sm">
        {/* Brand */}
        <div className="flex h-16 items-center px-5">
          <Link href="/" className="flex items-center">
            <OutraLogo size="sm" />
          </Link>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2">
          {navigation.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.name}
                href={item.href}
                className={cn(
                  "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "text-foreground"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                )}
              >
                {isActive && (
                  <motion.div
                    layoutId="sidebar-active"
                    className="absolute inset-0 rounded-lg border border-border bg-card shadow-[0px_1px_2px_0px_rgba(0,0,0,0.06)]"
                    transition={{ type: "spring", stiffness: 500, damping: 38 }}
                  />
                )}
                <item.icon
                  className={cn(
                    "relative z-10 h-4 w-4 shrink-0 transition-transform group-hover:scale-110",
                    isActive && "text-accent1"
                  )}
                />
                <span className="relative z-10 flex-1">{item.name}</span>
                {item.badge != null && item.badge > 0 && (
                  <span
                    className={cn(
                      "relative z-10 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold",
                      isActive ? "bg-accent1/10 text-accent1" : "bg-muted text-muted-foreground"
                    )}
                  >
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        {/* Run controls */}
        <div className="space-y-2 px-3 py-2">
          <div className="flex items-center gap-1.5 px-2 py-1">
            <span className="relative flex h-1.5 w-1.5">
              {running && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent1 opacity-75" />
              )}
              <span
                className={cn(
                  "relative inline-flex h-1.5 w-1.5 rounded-full",
                  running ? "bg-accent1" : "bg-emerald-500"
                )}
              />
            </span>
            <span className="text-[11px] font-medium text-muted-foreground">
              {running ? "Running" : "Idle"}
            </span>
          </div>

          <AnimatePresence initial={false}>
            {running && (
              <motion.button
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                whileTap={{ scale: 0.98 }}
                onClick={abort}
                disabled={aborting}
                title="Abort the current run"
                className="inline-flex w-full items-center justify-center gap-1.5 overflow-hidden whitespace-nowrap rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-60"
              >
                {aborting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Square className="h-3 w-3 fill-current" />
                )}
                {aborting ? "Aborting" : "Abort run"}
              </motion.button>
            )}
          </AnimatePresence>

          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => setRunOpen(true)}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg accent-gradient px-3.5 py-2 text-sm font-medium text-white shadow-[0_4px_12px_-4px_hsl(var(--accent-1)/0.6)]"
          >
            {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {running ? "Running" : "Run pipeline"}
          </motion.button>
        </div>

        {/* User card */}
        <div className="p-3">
          <div className="flex items-center gap-2.5 rounded-xl bg-primary px-3 py-2.5 text-primary-foreground">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full accent-gradient text-xs font-semibold text-white">
              {user?.photoURL ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={user.photoURL} alt={displayName} className="h-full w-full object-cover" />
              ) : (
                initial
              )}
            </span>
            <Link href="/profile" className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold leading-tight">{displayName}</p>
              <p className="truncate text-[11px] text-primary-foreground/60">Pro plan</p>
            </Link>
            <button
              onClick={handleSignOut}
              title="Sign out"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-primary-foreground/60 transition-colors hover:bg-white/10 hover:text-primary-foreground"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </aside>

      <RunPipelineDialog open={runOpen} onOpenChange={setRunOpen} />
    </>
  );
}
