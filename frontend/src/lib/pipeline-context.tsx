"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { api, type PipelineRunState } from "@/lib/api";

interface PipelineContextValue {
  state: PipelineRunState | null;
  refresh: () => Promise<PipelineRunState | null>;
}

const PipelineContext = createContext<PipelineContextValue | null>(null);

/**
 * A SINGLE shared poller for the pipeline run-status.
 *
 * Every component reads from this one context instead of starting its own
 * polling loop — that's what was previously hammering /api/pipeline/run-status
 * (one request per mounted RunPipelineButton/Dialog/TopBar). Here there's
 * exactly one loop for the whole app.
 *
 * Cadence:
 *   - fast (activeMs) while a run is in progress
 *   - slow (idleMs) while idle
 *   - paused entirely while the browser tab is hidden
 */
export function PipelineProvider({
  children,
  activeMs = 2000,
  idleMs = 20000,
}: {
  children: React.ReactNode;
  activeMs?: number;
  idleMs?: number;
}) {
  const [state, setState] = useState<PipelineRunState | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlight.current) return null;
    inFlight.current = true;
    try {
      const s = await api.pipeline.runStatus();
      if (mounted.current) setState(s);
      return s;
    } catch {
      return null;
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;

    async function tick() {
      // Skip work when the tab is hidden — resume on visibility change.
      if (typeof document !== "undefined" && document.hidden) {
        timer.current = setTimeout(tick, idleMs);
        return;
      }
      const s = await refresh();
      const delay = s?.running ? activeMs : idleMs;
      timer.current = setTimeout(tick, delay);
    }

    tick();

    const onVisible = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      mounted.current = false;
      if (timer.current) clearTimeout(timer.current);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh, activeMs, idleMs]);

  return (
    <PipelineContext.Provider value={{ state, refresh }}>
      {children}
    </PipelineContext.Provider>
  );
}

/**
 * Read the shared pipeline status. Safe to call from many components —
 * they all share the single provider poll loop (no extra requests).
 */
export function usePipelineStatus() {
  const ctx = useContext(PipelineContext);
  if (!ctx) {
    // Fallback so components don't crash if used outside the provider.
    return { state: null as PipelineRunState | null, refresh: async () => null };
  }
  return ctx;
}
