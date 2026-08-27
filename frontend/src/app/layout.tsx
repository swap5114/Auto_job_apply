import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { AuthProvider } from "@/lib/auth-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "AutoApply — Job Pipeline Dashboard",
  description: "Minimalist dashboard for managing your automated job application pipeline",
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
      </body>
    </html>
  );
}
