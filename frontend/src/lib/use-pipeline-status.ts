"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type PipelineRunState } from "@/lib/api";

/**
 * Polls the backend for the live pipeline run status.
 *
 * Polls faster (every `activeMs`) while a run is in progress, and slower
 * (every `idleMs`) when idle, to keep the "Running / Idle" indicator fresh
 * without hammering the API.
 */
export function usePipelineStatus(activeMs = 1500, idleMs = 5000) {
  const [state, setState] = useState<PipelineRunState | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const s = await api.pipeline.runStatus();
      if (mounted.current) setState(s);
      return s;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;

    async function tick() {
      const s = await refresh();
      const delay = s?.running ? activeMs : idleMs;
      timer.current = setTimeout(tick, delay);
    }
    tick();

    return () => {
      mounted.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [refresh, activeMs, idleMs]);

  return { state, refresh };
}
