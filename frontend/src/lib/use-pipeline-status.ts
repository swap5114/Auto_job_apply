"use client";

/**
 * Kept for backwards-compatible imports. The real implementation now lives in
 * pipeline-context.tsx as a single shared poller — this just re-exports it so
 * every consumer shares one polling loop instead of starting its own.
 */
export { usePipelineStatus } from "@/lib/pipeline-context";
