"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

/**
 * Route guard for the (dashboard) route group (Phase 3.5). Redirects to
 * /signin if there's no authenticated user once Firebase has finished its
 * initial auth-state check -- previously this layout rendered
 * unconditionally with no guard at all.
 *
 * Renders nothing (past the loading spinner) while unauthenticated so the
 * dashboard's real content/data fetches never mount for a signed-out
 * visitor, even for the instant before the redirect takes effect.
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/signin");
    }
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return <>{children}</>;
}
