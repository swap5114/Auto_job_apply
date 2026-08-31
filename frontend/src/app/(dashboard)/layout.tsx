import { TopBar } from "@/components/layout/topbar";
import { PipelineProvider } from "@/lib/pipeline-context";
import { RequireAuth } from "@/components/layout/require-auth";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <RequireAuth>
      <PipelineProvider>
        <div className="relative min-h-screen">
          {/* Ambient canvas texture */}
          <div className="pointer-events-none fixed inset-0 -z-10 dot-grid opacity-[0.4]" />
          <div className="pointer-events-none fixed inset-x-0 top-0 -z-10 h-72 radial-glow opacity-70" />

          <TopBar />

          {/* Content — padded to clear the floating top bar */}
          <main className="mx-auto max-w-6xl px-4 pt-24">{children}</main>
        </div>
      </PipelineProvider>
    </RequireAuth>
  );
}
