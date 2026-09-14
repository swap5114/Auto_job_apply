import { LegalPage, LegalSection as Section } from "@/components/marketing/legal-page";

export const metadata = {
  title: "Terms of Service — Outra",
  description: "The terms for using Outra.",
};

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service">

      <Section title="The service">
        <p>
          Outra helps you find companies, tailor your resume, and draft personalized
          outreach. Nothing is sent without your explicit approval. You are responsible for the
          content of any message you approve and send.
        </p>
      </Section>

      <Section title="Acceptable use">
        <p>
          Use Outra only for your own genuine job search. Do not use it to send spam, harass
          recipients, or misrepresent your background. Every message must be truthful — the
          product is built to avoid fabrication, and you agree not to edit drafts to include
          false claims. Respect recipients&apos; requests to stop being contacted.
        </p>
      </Section>

      <Section title="Your Gmail">
        <p>
          If you connect Gmail, you authorize Outra to create drafts and send the specific
          messages you approve from your account, and to check for replies to enable follow-ups.
          You can revoke this access at any time in Settings or your Google account settings.
        </p>
      </Section>

      <Section title="No guarantees">
        <p>
          Outra is provided as-is, without warranty. We don&apos;t guarantee interviews,
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
    </LegalPage>
  );
}
