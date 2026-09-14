import { MarketingNav } from "@/components/marketing/marketing-nav";
import { Footer } from "@/components/marketing/footer";

/**
 * Shared shell for long-form legal pages (privacy, terms) so they share one
 * container width, gutter, and title treatment instead of each rolling their
 * own. Reading-width (`max-w-3xl`) is intentional for prose.
 */
export function LegalPage({
  title,
  updated = "2026",
  children,
}: {
  title: string;
  updated?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen">
      <MarketingNav />
      <main className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="font-display text-3xl text-foreground sm:text-4xl">{title}</h1>
        <p className="mt-3 text-sm text-muted-foreground">Last updated: {updated}</p>
        {children}
      </main>
      <Footer />
    </div>
  );
}

export function LegalSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-8">
      <h2 className="font-display text-xl text-foreground">{title}</h2>
      <div className="mt-2 space-y-3 text-sm leading-relaxed text-muted-foreground">
        {children}
      </div>
    </section>
  );
}
