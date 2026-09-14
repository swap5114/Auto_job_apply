// Grayscale "where users have been hired" wall (Tsenta-style).
// Uses text wordmarks instead of real brand assets to avoid trademark issues.

const companies = [
  "J.P.Morgan",
  "Intel",
  "Netflix",
  "Roblox",
  "Cisco",
  "NVIDIA",
  "Adobe",
  "Stripe",
  "Ramp",
  "Vercel",
  "Linear",
  "Datadog",
];

export function LogoCloud() {
  return (
    <div className="mx-auto max-w-5xl px-6">
      <p className="eyebrow text-center">Where Outra users have been hired</p>
      <div className="mt-8 grid grid-cols-3 items-center gap-x-8 gap-y-8 sm:grid-cols-4 md:grid-cols-6">
        {companies.map((name) => (
          <span
            key={name}
            className="text-center text-base font-semibold tracking-tight text-foreground/35 transition-colors duration-300 hover:text-foreground/70"
          >
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
