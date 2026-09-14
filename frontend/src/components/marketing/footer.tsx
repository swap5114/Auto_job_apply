import Link from "next/link";

const COLUMNS: { heading: string; links: { label: string; href: string }[] }[] = [
  {
    heading: "Product",
    links: [
      { label: "How it works", href: "#pipeline" },
      { label: "Dashboard", href: "/dashboard" },
      { label: "FAQ", href: "#faq" },
    ],
  },
  {
    heading: "What it does",
    links: [
      { label: "Sourcing", href: "#pipeline" },
      { label: "Resume tailoring", href: "#pipeline" },
      { label: "Outreach drafts", href: "#pipeline" },
      { label: "Review queue", href: "#pipeline" },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "Sign in", href: "/signin" },
      { label: "Get started", href: "/signin" },
    ],
  },
  {
    heading: "Legal",
    links: [
      { label: "Privacy", href: "/privacy" },
      { label: "Terms", href: "/terms" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="relative overflow-hidden bg-[#0a0a0b] text-white">
      <div className="mx-auto max-w-6xl px-6 pt-16">
        {/* Link columns */}
        <div className="grid grid-cols-2 gap-10 sm:grid-cols-4">
          {COLUMNS.map((col) => (
            <div key={col.heading}>
              <p className="text-xs font-semibold text-white">{col.heading}</p>
              <ul className="mt-4 space-y-3">
                {col.links.map((link) => (
                  <li key={link.label}>
                    <Link
                      href={link.href}
                      className="text-xs text-white/50 transition-colors hover:text-white"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Meta row */}
        <div className="mt-14 flex flex-col items-start justify-between gap-3 border-t border-white/10 py-6 sm:flex-row sm:items-center">
          <p className="text-xs text-white/50">
            © {new Date().getFullYear()} Outra. You approve every message before it goes out.
          </p>
          <p className="text-xs text-white/40">Built by a solo developer.</p>
        </div>
      </div>

      {/* Giant faded wordmark (Plane-style watermark) */}
      <div
        aria-hidden
        className="pointer-events-none select-none px-6 pb-2"
      >
        <span className="block text-center font-display-tight text-[24vw] leading-[0.8] text-white/[0.05] md:text-[22vw]">
          Outra
        </span>
      </div>
    </footer>
  );
}
