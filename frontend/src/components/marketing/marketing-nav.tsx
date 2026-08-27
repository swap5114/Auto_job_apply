"use client";

import Link from "next/link";
import { Zap, ChevronRight } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

const navLinks = [
  { name: "Features", href: "#features" },
  { name: "Pipeline", href: "#pipeline" },
  { name: "Pricing", href: "#pricing" },
];

export function MarketingNav() {
  // Signed-in visitors go straight to the dashboard; everyone else goes
  // through /signin first (Phase 3.5) -- previously both links pointed at
  // /dashboard unconditionally, before any auth existed.
  const { user } = useAuth();
  const primaryHref = user ? "/dashboard" : "/signin";

  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary">
            <Zap className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="font-display text-lg text-foreground">AutoApply</span>
        </Link>

        {/* Nav Links */}
        <nav className="hidden items-center gap-8 md:flex">
          {navLinks.map((link) => (
            <Link
              key={link.name}
              href={link.href}
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              {link.name}
            </Link>
          ))}
        </nav>

        {/* Actions */}
        <div className="flex items-center gap-3">
          <Link
            href={primaryHref}
            className="text-sm font-medium text-foreground transition-colors hover:text-muted-foreground"
          >
            {user ? "Dashboard" : "Sign in"}
          </Link>
          <Link
            href={primaryHref}
            className="inline-flex items-center gap-1 rounded-[10px] bg-primary px-3.5 py-2 text-sm font-medium text-primary-foreground shadow-button-brand transition-all hover:shadow-button-brand-hover"
          >
            Get started
            <ChevronRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>
    </header>
  );
}
