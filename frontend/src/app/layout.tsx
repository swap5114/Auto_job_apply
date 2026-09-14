import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Toaster } from "sonner";
import { AuthProvider } from "@/lib/auth-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "Outra — AI Cold Outreach & Job Pipeline",
  description: "Personalized cold outreach to hiring startups — you approve every message.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="font-sans antialiased">
        {/* AuthProvider lives at the root (not just the dashboard layout) so
            both the marketing page's "Sign in with Google" button and the
            dashboard's route guard share the exact same onAuthStateChanged
            subscription -- see lib/auth-context.tsx. */}
        <AuthProvider>{children}</AuthProvider>
        {/* Global toaster so feedback works everywhere -- including the public
            landing page's hero chat, not just the dashboard. */}
        <Toaster position="bottom-right" richColors />
      </body>
    </html>
  );
}
