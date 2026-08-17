import Link from "next/link";
import { Zap } from "lucide-react";

export function Footer() {
  return (
    <footer className="border-t border-border/60">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 py-10 md:flex-row">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary">
            <Zap className="h-3.5 w-3.5 text-primary-foreground" />
          </div>
          <span className="font-display text-base text-foreground">AutoApply</span>
        </div>
        <p className="text-xs text-muted-foreground">
          A LangGraph-orchestrated job application pipeline.
        </p>
        <div className="flex items-center gap-6 text-sm text-muted-foreground">
          <Link href="/dashboard" className="transition-colors hover:text-foreground">
            Dashboard
          </Link>
          <Link href="#features" className="transition-colors hover:text-foreground">
            Features
          </Link>
        </div>
      </div>
    </footer>
  );
}
