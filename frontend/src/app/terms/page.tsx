import { MarketingNav } from "@/components/marketing/marketing-nav";
import { Footer } from "@/components/marketing/footer";

export const metadata = {
  title: "Terms of Service — AutoApply",
  description: "The terms for using AutoApply.",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="font-display text-xl text-foreground">{title}</h2>
      <div className="mt-2 space-y-3 text-sm leading-relaxed text-muted-foreground">{children}</div>
    </section>
  );
}

export default function TermsPage() {
  return (
    <div className="min-h-screen">
      <MarketingNav />
      <main className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="font-display text-4xl text-foreground">Terms of Service</h1>
        <p className="mt-3 text-sm text-muted-foreground">Last updated: 2026</p>

        <Section title="The service">
          <p>
            AutoApply helps you find companies, tailor your resume, and draft personalized
            outreach. Nothing is sent without your explicit approval. You are responsible for the
            content of any message you approve and send.
          </p>
        </Section>

        <Section title="Acceptable use">
          <p>
            Use AutoApply only for your own genuine job search. Do not use it to send spam, harass
            recipients, or misrepresent your background. Every message must be truthful — the
            product is built to avoid fabrication, and you agree not to edit drafts to include
            false claims. Respect recipients&apos; requests to stop being contacted.
          </p>
        </Section>

        <Section title="Your Gmail">
          <p>
            If you connect Gmail, you authorize AutoApply to create drafts and send the specific
            messages you approve from your account, and to check for replies to enable follow-ups.
            You can revoke this access at any time in Settings or your Google account settings.
          </p>
        </Section>

        <Section title="No guarantees">
          <p>
            AutoApply is provided as-is, without warranty. We don&apos;t guarantee interviews,
            replies, or outcomes. Third-party data (company matches, contact emails) may be
            incomplete or inaccurate.
          </p>
        </Section>

        <Section title="Changes">
          <p>
            We may update these terms as the product evolves. Continued use after an update means
            you accept the revised terms.
          </p>
        </Section>
      </main>
      <Footer />
    </div>
  );
}
