// Wordmark-style logo cloud (like Cal.com's "trusted by" bar).
// Uses text wordmarks instead of real brand assets to avoid trademark issues.

const companies = [
  "Arbeitnow",
  "Jobicy",
  "Greenhouse",
  "Lever",
  "Ashby",
  "Workable",
];

export function LogoCloud() {
  return (
    <div className="mx-auto flex max-w-5xl flex-col items-center gap-6 px-6 md:flex-row md:justify-between">
      <p className="max-w-[180px] text-sm leading-snug text-muted-foreground">
        Sourcing leads from the boards you already trust
      </p>
      <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-4">
        {companies.map((name) => (
          <span
            key={name}
            className="text-lg font-semibold tracking-tight text-foreground/70 grayscale transition-opacity hover:opacity-100"
          >
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
