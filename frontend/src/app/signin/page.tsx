"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { OutraLogo } from "@/components/ui/outra-logo";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth-context";
import { api } from "@/lib/api";
import { getAnonSession, clearAnonSession } from "@/lib/anon-session";

/**
 * Sign-in entry point (Phase 3.5) + anon -> account conversion (Phase 3.6).
 *
 * If the visitor already has an in-memory (sessionStorage-backed) result
 * from the anonymous resume-upload hook, it's converted into a real saved
 * resume + search criteria right after sign-in, then the visitor lands on
 * the dashboard with their data already there -- no re-upload, no second
 * "session migration" step. Visitors who sign in without ever using the
 * anonymous flow skip straight to the dashboard with an empty profile.
 */
export default function SignInPage() {
  const { user, signInWithGoogle, loading: authLoading } = useAuth();
  const router = useRouter();
  const [signingIn, setSigningIn] = useState(false);

  useEffect(() => {
    // If already signed in when reaching this page, skip to dashboard.
    if (!authLoading && user) {
      router.replace("/dashboard");
    }
  }, [user, authLoading, router]);

  async function handleGoogleSignIn() {
    try {
      setSigningIn(true);
      const authenticatedUser = await signInWithGoogle();

      // Convert any anonymous session data created before sign-in (Phase 3.6)
      const anonData = getAnonSession();
      if (anonData) {
        try {
          await api.account.convertAnonSession(
            anonData.parsed_resume,
            anonData.inferred_criteria,
          );
          clearAnonSession();
        } catch (e: any) {
          console.error("Failed to convert anonymous session:", e);
          toast.error("Signed in, but saving your initial resume data failed. You can re-upload on your Profile page.");
        }
      }

      router.replace("/dashboard");
    } catch (e: any) {
      toast.error(e?.message || "Sign-in failed. Please try again.");
    } finally {
      setSigningIn(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 px-6">
      <Link href="/" className="flex items-center">
        <OutraLogo size="lg" />
      </Link>

      <div className="w-full max-w-sm rounded-2xl border bg-card p-8 text-center shadow-dropdown">
        <h1 className="font-display text-2xl text-foreground sm:text-3xl">Sign in to continue</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Save your resume, matches, and outreach — all tied to your account.
        </p>

        <Button
          variant="outline"
          size="lg"
          onClick={handleGoogleSignIn}
          disabled={signingIn || authLoading}
          className="mt-6 w-full gap-2.5"
        >
          {signingIn ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <GoogleIcon className="h-4 w-4" />
          )}
          Continue with Google
        </Button>
      </div>
    </div>
  );
}

function GoogleIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47c-.29 1.48-1.14 2.73-2.4 3.58v2.97h3.86c2.26-2.09 3.56-5.17 3.56-8.79z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-2.97c-1.07.72-2.44 1.14-4.07 1.14-3.13 0-5.78-2.11-6.73-4.96H1.29v3.07C3.26 21.3 7.31 24 12 24z"
      />
      <path
        fill="#FBBC05"
        d="M5.27 14.3a7.19 7.19 0 0 1 0-4.6V6.63H1.29a11.98 11.98 0 0 0 0 10.74l3.98-3.07z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.94 1.19 15.24 0 12 0 7.31 0 3.26 2.7 1.29 6.63l3.98 3.07C6.22 6.86 8.87 4.75 12 4.75z"
      />
    </svg>
  );
}
