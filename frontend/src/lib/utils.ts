import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// eslint-disable-next-line no-control-regex
const ANSI_PATTERN = /\x1b\[[0-9;]*[a-zA-Z]/g;

/**
 * Strips ANSI escape/color codes from terminal output.
 *
 * Kiro CLI's chat output (surfaced via the build's logs_tail field) is
 * colorized for a real terminal — without this, raw escape sequences show
 * up as garbled text (e.g. "\u001b[38;5;141m") in a plain <pre> block.
 */
export function stripAnsi(text: string): string {
  return text.replace(ANSI_PATTERN, "");
}

// ---------------------------------------------------------------------------
// Active demo-build tracking (per lead)
// ---------------------------------------------------------------------------
// DemoBuilder's poll state (stage, buildId, status) previously lived only in
// component-local useState, which React throws away on unmount. Since the
// ResearchPanel/DemoBuilder tree remounts fresh every time a lead's detail
// Sheet is closed and reopened (and research itself re-generates a new,
// different demo_project on every "Run Research" click), a build that was
// still running server-side became invisible client-side the moment you
// navigated away — the UI would just show the idle "Build This Demo" button
// again, with no indication a build was in flight.
//
// The build itself always outlives the component (it's tracked server-side
// in api/main.py's _demo_builds dict, keyed by build_id, independent of
// whatever demo_project happens to be displayed right now). So the fix is
// to persist just the build_id per lead in localStorage, and have
// DemoBuilder check for one on mount to resume polling immediately instead
// of defaulting to "idle".

const ACTIVE_BUILD_KEY_PREFIX = "autoapply.activeBuild.";

export function getActiveBuildId(leadId: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACTIVE_BUILD_KEY_PREFIX + leadId);
  } catch {
    return null; // localStorage can throw in private-browsing/storage-full edge cases
  }
}

export function setActiveBuildId(leadId: string, buildId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ACTIVE_BUILD_KEY_PREFIX + leadId, buildId);
  } catch {
    // Non-fatal — worst case the build just isn't recoverable after a remount.
  }
}

export function clearActiveBuildId(leadId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(ACTIVE_BUILD_KEY_PREFIX + leadId);
  } catch {
    // ignore
  }
}
