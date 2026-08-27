"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  FileText,
  CheckCircle2,
  Settings,
  Zap,
  Play,
  Loader2,
  Hammer,
  UserRound,
  LogOut,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api, type Stats } from "@/lib/api";
import { usePipelineStatus } from "@/lib/use-pipeline-status";
import { RunPipelineDialog } from "@/components/pipeline/run-pipeline-dialog";
import { useAuth } from "@/lib/auth-context";

export function TopBar() {
  const pathname = usePathname();
  const [scrolled, setScrolled] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const [runOpen, setRunOpen] = useState(false);

  const { state } = usePipelineStatus();
  const running = state?.running ?? false;

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Fetch real counts for nav badges once on mount. Stats reads hit Google
  // Sheets (slow + rate-limited), so we do NOT poll on an interval — badges
  // refresh only when a pipeline run finishes (below).
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

  // Refresh badges shortly after a run completes
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
    { name: "Leads", href: "/leads", icon: FileText, badge: leadsBadge },
    { name: "Review", href: "/review", icon: CheckCircle2, badge: reviewBadge },
    { name: "Builds", href: "/builds", icon: Hammer, badge: null as number | null },
    { name: "Profile", href: "/profile", icon: UserRound, badge: null as number | null },
    { name: "Settings", href: "/settings", icon: Settings, badge: null as number | null },
  ];

  const { signOut } = useAuth();
  const router = useRouter();

  async function handleSignOut() {
    await signOut();
    router.replace("/");
  }

  return (
    <motion.header
      initial={{ y: -80, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ type: "spring", stiffness: 260, damping: 26, delay: 0.05 }}
      className="fixed inset-x-0 top-3 z-50 px-4"
    >
      <motion.div
        animate={{
          maxWidth: scrolled ? 880 : 1080,
          boxShadow: scrolled
            ? "0px 5px 20px 0px rgba(0,0,0,0.10), 0px 10px 40px 0px rgba(0,0,0,0.04)"
            : "0px 1px 1px 0px rgba(0,0,0,0.05), 0px 2px 8px 0px rgba(0,0,0,0.04)",
        }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        className="glass mx-auto flex h-14 items-center justify-between gap-2 rounded-2xl border px-3"
      >
        {/* Logo */}
        <Link href="/" className="flex shrink-0 items-center gap-2 pl-1 pr-2">
          <motion.div
            whileHover={{ rotate: -12, scale: 1.08 }}
            transition={{ type: "spring", stiffness: 400, damping: 15 }}
            className="flex h-8 w-8 items-center justify-center rounded-lg accent-gradient shadow-[0_2px_8px_-2px_hsl(var(--accent-1)/0.5)]"
          >
            <Zap className="h-4 w-4 text-white" />
          </motion.div>
          <span className="hidden font-display text-base leading-none text-foreground sm:block">
            AutoApply
          </span>
        </Link>

        {/* Center nav */}
        <nav className="flex items-center gap-0.5">
          {navigation.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.name}
                href={item.href}
                className={cn(
                  "group relative flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
                  isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {isActive && (
                  <motion.div
                    layoutId="topbar-active"
                    className="absolute inset-0 rounded-xl border border-border bg-card shadow-[0px_1px_2px_0px_rgba(0,0,0,0.06)]"
                    transition={{ type: "spring", stiffness: 500, damping: 38 }}
                  />
                )}
                <item.icon
                  className={cn(
                    "relative z-10 h-4 w-4 transition-transform group-hover:scale-110",
                    isActive && "text-accent1"
                  )}
                />
                <span className="relative z-10 hidden md:block">{item.name}</span>
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

        {/* Right: status + action */}
        <div className="flex shrink-0 items-center gap-2 pr-1">
          <AnimatePresence>
            {!scrolled && (
              <motion.div
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: "auto" }}
                exit={{ opacity: 0, width: 0 }}
                className="hidden items-center gap-1.5 overflow-hidden whitespace-nowrap rounded-full bg-muted/70 px-2.5 py-1 lg:flex"
              >
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
              </motion.div>
            )}
          </AnimatePresence>

          <motion.button
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
            onClick={() => setRunOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-xl accent-gradient px-3.5 py-2 text-sm font-medium text-white shadow-[0_4px_12px_-4px_hsl(var(--accent-1)/0.6)]"
          >
            {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            <span className="hidden sm:block">{running ? "Running" : "Run"}</span>
          </motion.button>

          <button
            onClick={handleSignOut}
            title="Sign out"
            className="flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </motion.div>

      <RunPipelineDialog open={runOpen} onOpenChange={setRunOpen} />
    </motion.header>
  );
}
