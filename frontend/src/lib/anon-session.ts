/**
 * Storage for the anonymous pre-signup hook's in-memory result (Phase 2:
 * /api/anon/resume's parsed_resume + inferred_criteria), so it survives
 * the Google sign-in popup round-trip and can be converted into a real
 * account right after (Phase 3.6).
 *
 * Backed by sessionStorage rather than plain React state: sign-in is a
 * popup flow (no full page navigation), so state would usually survive
 * anyway, but sessionStorage also covers a same-tab redirect-based sign-in
 * fallback without extra plumbing, and clears itself when the tab closes
 * (this is *not* meant to persist beyond the current visit).
 */

const STORAGE_KEY = "autoapply_anon_session";

export interface AnonSession {
  parsed_resume: object;
  inferred_criteria: object;
}

export function saveAnonSession(session: AnonSession) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // sessionStorage can throw in some locked-down/private-browsing
    // contexts -- losing this is a UX regression (re-upload required),
    // not a functional break, so we swallow it.
  }
}

export function getAnonSession(): AnonSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AnonSession;
  } catch {
    return null;
  }
}

export function clearAnonSession() {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // no-op
  }
}
