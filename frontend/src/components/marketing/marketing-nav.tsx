"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { OutraLogo } from "@/components/ui/outra-logo";
import { Button } from "@/components/ui/button";

const navLinks = [
  { name: "How it works", href: "#pipeline" },
  { name: "Platforms", href: "#pipeline" },
  { name: "FAQ", href: "#faq" },
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
        <Link href="/" className="flex items-center">
          <OutraLogo size="md" animated />
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
          <Button asChild size="sm">
            <Link href={primaryHref}>
              Get started
              <ChevronRight className="ml-1 h-3.5 w-3.5" />
            </Link>
          </Button>
        </div>
      </div>
    </header>
  );
}
