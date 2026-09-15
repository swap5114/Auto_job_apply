import { Sidebar } from "@/components/layout/sidebar";
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

          {/* Left navigation sidebar (fixed) */}
          <Sidebar />

          {/* Content — full width, offset by the sidebar. */}
          <main className="min-h-screen pl-[248px]">
            <div className="px-6 py-8 lg:px-10">{children}</div>
          </main>
        </div>
      </PipelineProvider>
    </RequireAuth>
  );
}
