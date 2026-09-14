import Link from "next/link";
import { LegalPage, LegalSection as Section } from "@/components/marketing/legal-page";

export const metadata = {
  title: "Privacy Policy — Outra",
  description: "How Outra handles your data.",
};

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy">

      <Section title="What we collect">
        <p>
          When you sign in with Google we store your account&apos;s email and a stable user id.
          When you use the product we store the resume you upload, the search criteria we infer
          from it, and the leads (companies, roles, contacts, tailored resumes, and outreach
          drafts) generated for you. If you connect Gmail, we store an encrypted OAuth refresh
          token — never your Google password.
        </p>
      </Section>

      <Section title="How we use it">
        <p>
          Your data is used solely to operate the product for you: matching you to companies,
          tailoring your resume, drafting outreach, and — only for messages you explicitly
          approve — sending email from your connected Gmail and checking for replies. We do not
          sell your data or use it for advertising.
        </p>
      </Section>

      <Section title="Google / Gmail data">
        <p>
          Outra&apos;s use of information received from Google APIs adheres to the{" "}
          <a
            className="underline"
            href="https://developers.google.com/terms/api-services-user-data-policy"
            target="_blank"
            rel="noopener noreferrer"
          >
            Google API Services User Data Policy
          </a>
          , including the Limited Use requirements. We request only the Gmail scopes needed to
          create drafts and send the outreach you approve, and to detect replies for follow-ups.
          We do not read, store, or transmit the contents of your mailbox beyond what is needed
          for these features.
        </p>
      </Section>

      <Section title="Third-party processors">
        <p>
          To provide the service we send limited data to: Google (authentication, Gmail sending),
          an LLM provider (Anthropic and/or Google) to tailor resumes and draft outreach, and
          contact-discovery providers (Apollo.io, Hunter.io) to find a company&apos;s public
          contact. We share only what each step requires.
        </p>
      </Section>

      <Section title="Retention & deletion">
        <p>
          You can disconnect Gmail at any time in Settings, which deletes the stored token.
          Contact us to delete your account and associated data; deleting your account removes
          your resume, criteria, and leads.
        </p>
      </Section>

      <Section title="Contact">
        <p>
          Questions about this policy? Reach out via the email on our{" "}
          <Link className="underline" href="/">
            home page
          </Link>
          .
        </p>
      </Section>
    </LegalPage>
  );
}
