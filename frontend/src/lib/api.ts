/**
 * API client for the AutoApply backend.
 *
 * In development, Next.js rewrites /api/* to localhost:8000/api/*
 * via next.config.js, so we just use relative paths.
 */

const BASE = "/api";

// Set once by AuthProvider (lib/auth-context.tsx) on mount -- this is the
// one chokepoint (Phase 3.5) that lets every existing api.* call below
// start carrying a real Authorization header without touching any of
// them individually. Returns null before sign-in / for the anonymous
// pre-signup flow, which intentionally never sends a token.
let getAuthToken: (() => Promise<string | null>) | null = null;

export function setAuthTokenGetter(getter: (() => Promise<string | null>) | null) {
  getAuthToken = getter;
}

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(options?.headers as Record<string, string> | undefined),
  };

  if (getAuthToken) {
    const token = await getAuthToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const res = await fetch(`${BASE}${path}`, {
    headers,
    ...options,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error: ${res.status}`);
  }

  return res.json();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Lead {
  id: string;
  source: string;
  company: string;
  role: string;
  jd_text: string;
  contact_name: string;
  contact_email: string;
  x_handle: string;
  status: string;
  resume_version: string;
  outreach_draft: string;
  sent_at: string;
  last_checked: string;
  followup_count: string;
  listing_url: string;
  posted_date: string;
  domain: string;
  review_decision: string;
  // ATS keyword-coverage % for the tailored resume (0-100), or null if the
  // resume hasn't been tailored yet.
  keyword_coverage: number | null;
  // Phase 5 (Apply channel) additions.
  channel: string[];
  cover_note: string;
  applied_at: string;
  replied_at: string;
  failure_reason: string;
  job_id: string;
}

export interface MatchedJob {
  id: string;
  company_name: string;
  title: string;
  location: string | null;
  department: string | null;
  jd_text: string | null;
  apply_url: string | null;
  source: string;
  match_score: number;
  matched_signals: string[];
  already_saved_lead_id: string | null;
  already_saved_channel: string[];
}

export interface JobSearchResult {
  /** "catalog" = already synced (actively hiring); "live_yc" = cold-mail candidate. */
  origin: "catalog" | "live_yc";
  /** Catalog job id (null for a live_yc result until it's saved). */
  id: string | null;
  company_name: string;
  title: string;
  apply_url: string | null;
  source: string;
  is_hiring: boolean;
  slug: string | null;
  website: string | null;
  jd_text: string | null;
  already_saved_lead_id: string | null;
}

export interface JobSearchResponse {
  query: string;
  results: JobSearchResult[];
}

export interface BaseResume {
  resume_id: string | null;
  parsed_json: Record<string, unknown> | null;
  has_resume: boolean;
}

export type ResumeTemplate = "standard" | "jake";

/** Positional change-map for live highlighting (mirrors diff_resumes). */
export interface ResumeDiff {
  summary?: boolean;
  experience?: boolean[][];
  projects?: boolean[][];
  skills?: Record<string, boolean[]>;
}

export interface RephraseResult {
  base_json: Record<string, unknown>;
  tailored_json: Record<string, unknown>;
  keyword_coverage: number;
  ats_below_floor: boolean;
  model_used: string;
  escalated: boolean;
  template: ResumeTemplate;
  diff: ResumeDiff;
  jd_truncated: boolean;
  max_jd_chars: number;
}

export interface TailoredResumeItem {
  id: string;
  lead_id: string | null;
  company: string | null;
  role: string | null;
  keyword_coverage: number | null;
  template: ResumeTemplate;
  model_used: string | null;
  source: string;
  created_at: string;
  tailored_json: Record<string, unknown> | null;
}

export interface ParsedResume {
  name: string;
  contact: Record<string, unknown>;
  summary: string;
  education: Record<string, unknown>[];
  experience: Record<string, unknown>[];
  projects: Record<string, unknown>[];
  skills: Record<string, unknown>;
  certifications: string[];
}

export interface InferredCriteria {
  roles: string[];
  tech_stack: string[];
  seniority: string | null;
  locations: string[];
  remote_pref: string | null;
  inferred_from_resume: boolean;
}

export interface AnonResumeUploadResult {
  parsed_resume: ParsedResume;
  inferred_criteria: InferredCriteria;
  matched_jobs: MatchedJob[];
}

export interface DemoProject {
  title: string;
  description: string;
  tech_stack: string[];
  deliverable: string;
  time_estimate: string;
  why_impressive: string;
}

export interface CompanyResearch {
  overview: string;
  stage: string;
  industry: string;
  tech_signals: string[];
  demo_project: DemoProject;
  talking_points: string[];
  smart_questions: string[];
  fit_summary: string;
}

export interface Stats {
  total: number;
  new: number;
  pending_review: number;
  in_review: number;
  approved: number;
  draft_created: number;
  sent: number;
  replied: number;
  rejected: number;
}

export interface SearchCriteria {
  role_keywords: string[];
  tech_stack_keywords: string[];
  seniority_exclude_keywords: string[];
  non_tech_exclude_keywords: string[];
  years_experience_threshold: number;
  location_keywords: string[];
}

export interface ProfileSearchCriteria {
  roles: string[];
  tech_stack: string[];
  seniority: string | null;
  locations: string[];
  remote_pref: string | null;
  inferred_from_resume: boolean;
}

export interface ProfileResume {
  id: string;
  file_ref: string | null;
  parsed_json: Record<string, unknown> | null;
  is_primary: boolean;
  created_at: string;
}

export interface PipelineConfig {
  model_backend: string;
  followup_days: number;
  max_followups: number;
  gmail_direct_send: boolean;
}

export interface PipelineStep {
  step: string;
  status: "ok" | "error" | "running";
}

export interface PipelineRunState {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  current_step: string | null;
  steps: PipelineStep[];
  summary: {
    pipeline: string;
    ok: number;
    failed: number;
    steps: PipelineStep[];
  } | null;
  error: string | null;
}

export interface RunPipelineOptions {
  sources?: string[];
  yc_max_leads?: number;
  x_max_leads?: number;
  csv_path?: string;
}

// ---------------------------------------------------------------------------
// Demo builder (sandbox/orchestrator.py via api/main.py build-demo routes)
// ---------------------------------------------------------------------------

export type DemoBuildStage =
  | "pending"
  | "building"
  | "needs_secrets"
  | "success"
  | "failed";

export interface NeededSecret {
  name: string;
  why: string;
}

export interface DemoBuildResult {
  status: "success" | "failed";
  summary: string;
  build_command?: string;
  start_command?: string;
  entry_point?: string;
}

export type DemoDeployStage =
  | "exporting"
  | "pushing_github"
  | "deploying_vercel"
  | "deploying_render"
  | "deployed"
  | "deploy_failed";

export interface DemoBuildStatus {
  build_id: string;
  lead_id: string;
  running: boolean;
  stage: DemoBuildStage;
  attempt: number;
  max_attempts: number;
  needs_secrets: { needed: NeededSecret[] } | null;
  result: DemoBuildResult | null;
  error: string | null;
  logs_tail: string;
  deploy_stage: DemoDeployStage | null;
  deploy_error: string | null;
  repo_url: string | null;
  frontend_url: string | null;
  backend_url: string | null;
}

export interface DemoBuildSummary {
  build_id: string;
  lead_id?: string;
  title: string;
  company_name?: string;
  project_type?: "fullstack" | "frontend_only" | "backend_only";
  running: boolean;
  stage: DemoBuildStage;
  deploy_stage: DemoDeployStage | null;
  attempt: number;
  max_attempts: number;
  repo_url?: string | null;
  frontend_url?: string | null;
  backend_url?: string | null;
}

export type DemoBuildItem = DemoBuildSummary;

// ---------------------------------------------------------------------------
// Leads
// ---------------------------------------------------------------------------

export const api = {
  leads: {
    list: (status?: string) =>
      request<Lead[]>(status ? `/leads?status=${status}` : "/leads"),

    get: (id: string) => request<Lead>(`/leads/${id}`),

    approve: (id: string, channel?: "apply" | "outreach") =>
      request<{ status: string }>(
        `/leads/${id}/approve${channel ? `?channel=${channel}` : ""}`,
        { method: "POST" }
      ),

    reject: (id: string, channel?: "apply" | "outreach") =>
      request<{ status: string }>(
        `/leads/${id}/reject${channel ? `?channel=${channel}` : ""}`,
        { method: "POST" }
      ),

    edit: (id: string, outreach_draft: string) =>
      request<{ status: string }>(`/leads/${id}/edit`, {
        method: "POST",
        body: JSON.stringify({ outreach_draft }),
      }),

    // Remove a lead from the pipeline entirely (the inverse of jobs.save).
    // Used by the dashboard's "remove from pipeline" action on a saved match.
    remove: (id: string) =>
      request<{ status: string; lead_id: string }>(`/leads/${id}`, {
        method: "DELETE",
      }),

    // Auth is Bearer-token based (not cookies), so a plain <a href> to the
    // API route wouldn't carry the Authorization header -- this fetches
    // the PDF with the same auth headers every other api.* call uses and
    // hands back a blob: URL the caller can open in a new tab or set as
    // an <a href>/<iframe src>. Caller is responsible for
    // URL.revokeObjectURL(...) once done with it, same as any other
    // blob URL.
    getResumePdfBlobUrl: async (id: string) => {
      const headers: Record<string, string> = {};
      if (getAuthToken) {
        const token = await getAuthToken();
        if (token) headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(`${BASE}/leads/${id}/resume-pdf`, { headers });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Failed to fetch resume PDF: ${res.status}`);
      }
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    },

    research: (id: string, forceFresh = false) =>
      request<CompanyResearch>(`/leads/${id}/research${forceFresh ? "?force_fresh=true" : ""}`, { method: "POST" }),

    // Retry a stuck/failed lead -- clears its failure and re-runs processing.
    retry: (id: string) =>
      request<{ status: string; lead_id: string }>(`/leads/${id}/retry`, { method: "POST" }),

    buildDemo: (id: string, demo_project: DemoProject, max_attempts?: number) =>
      request<DemoBuildStatus>(`/leads/${id}/build-demo`, {
        method: "POST",
        body: JSON.stringify({ demo_project, max_attempts }),
      }),

    buildDemoStatus: (id: string, buildId: string) =>
      request<DemoBuildStatus>(`/leads/${id}/build-demo/${buildId}/status`),

    provideBuildSecrets: (id: string, buildId: string, secrets: Record<string, string>) =>
      request<DemoBuildStatus>(`/leads/${id}/build-demo/${buildId}/secrets`, {
        method: "POST",
        body: JSON.stringify({ secrets }),
      }),

    cancelBuild: (id: string, buildId: string) =>
      request<{ status: string; build_id: string }>(`/leads/${id}/build-demo/${buildId}/cancel`, {
        method: "POST",
      }),
  },

  builds: {
    list: () => request<DemoBuildSummary[]>("/demos/list"),
  },

  demos: {
    build: (data: {
      title: string;
      description: string;
      company_name?: string;
      tech_stack?: string[];
      project_type?: "fullstack" | "frontend_only" | "backend_only";
    }) => request<DemoBuildStatus>("/demos/build", { method: "POST", body: JSON.stringify(data) }),

    refine: (buildId: string, prompt: string) =>
      request<DemoBuildStatus>(`/demos/${buildId}/refine`, {
        method: "POST",
        body: JSON.stringify({ prompt }),
      }),

    get: (buildId: string) => request<DemoBuildStatus>(`/demos/build/${buildId}`),

    list: () => request<DemoBuildItem[]>("/demos"),

    quota: () =>
      request<{ date: string; used: number; limit: number; remaining: number }>("/demos/quota"),
  },

  user: {
    getProviderKeys: () =>
      request<{ has_github_token: boolean; has_vercel_token: boolean; has_render_api_key: boolean }>(
        "/user/provider-keys"
      ),

    updateProviderKeys: (data: {
      github_token?: string;
      vercel_token?: string;
      render_api_key?: string;
    }) =>
      request<{
        status: string;
        has_github_token: boolean;
        has_vercel_token: boolean;
        has_render_api_key: boolean;
      }>("/user/provider-keys", { method: "POST", body: JSON.stringify(data) }),

    getGithubOAuthUrl: () => request<{ auth_url: string }>("/auth/github/connect"),
    getVercelOAuthUrl: () => request<{ auth_url: string }>("/auth/vercel/connect"),
  },

  jobs: {
    // Signed-in equivalent of the anonymous /api/anon/resume feed --
    // matches the shared catalog against the caller's own SAVED search
    // criteria (Phase 6). Empty array (not an error) if the user has no
    // criteria saved yet.
    matched: () => request<MatchedJob[]>("/jobs/matched"),

    // Converts a shared-catalog matched job into a per-user outreach Lead.
    // v1 is outreach-only, so the server always creates an outreach lead.
    save: (jobId: string) =>
      request<Lead>(`/jobs/${jobId}/save`, {
        method: "POST",
        body: JSON.stringify({}),
      }),

    // Search YC companies by name for the Matches search bar. Returns two
    // tiers: "catalog" hits (already-synced, actively-hiring roles) and
    // "live_yc" hits (found in the full YC directory but not in our catalog
    // — e.g. not currently hiring — so the user can still cold-mail them).
    search: (q: string) =>
      request<JobSearchResponse>(`/jobs/search?q=${encodeURIComponent(q)}`),

    // Save a live-YC company (a "live_yc" search result) as a cold-outreach
    // lead. Materializes the catalog company/job server-side, then creates
    // the lead — returns the new Lead.
    saveCold: (body: {
      slug: string;
      company_name: string;
      website?: string | null;
      jd_text?: string | null;
      apply_url?: string | null;
    }) =>
      request<Lead>("/jobs/search/save", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  chat: {
    // Hero onboarding: attach a resume + type who you're targeting, get
    // matched YC startups. Multipart; requires auth (the hero gates send
    // behind Google sign-in).
    match: async (file: File, target: string) => {
      const form = new FormData();
      form.append("file", file);
      form.append("target", target);
      const headers: Record<string, string> = {};
      if (getAuthToken) {
        const token = await getAuthToken();
        if (token) headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(`${BASE}/chat/match`, { method: "POST", headers, body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Match failed: ${res.status}`);
      }
      return res.json() as Promise<AnonResumeUploadResult>;
    },
  },

  gmail: {
    // Whether the signed-in user has connected their own Gmail, plus their
    // send preference ("draft" | "direct").
    status: () =>
      request<{ connected: boolean; email: string | null; send_mode: "draft" | "direct" }>(
        "/gmail/status"
      ),

    // Returns Google's consent URL; the caller redirects the browser to it.
    connectUrl: (send_mode: "draft" | "direct") =>
      request<{ auth_url: string }>(`/gmail/connect?send_mode=${send_mode}`),

    setSendMode: (send_mode: "draft" | "direct") =>
      request<{ connected: boolean; email: string | null; send_mode: "draft" | "direct" }>(
        "/gmail/send-mode",
        { method: "PUT", body: JSON.stringify({ send_mode }) }
      ),

    disconnect: () =>
      request<{ status: string }>("/gmail/disconnect", { method: "POST" }),
  },

  stats: {
    get: () => request<Stats>("/stats"),
  },

  outreach: {
    // Outreach quota for the current month — the backend source of truth
    // (GET /api/outreach/quota). `used` counts leads sent this month; `limit`
    // is derived server-side from the user's plan.
    quota: () =>
      request<{ plan: string; used: number; limit: number; remaining: number; reset: string }>(
        "/outreach/quota"
      ),
  },

  pipeline: {
    // On-demand full pipeline run (the "Run Pipeline" button)
    run: (opts?: RunPipelineOptions) =>
      request<{ status: string; sources: string[] }>("/pipeline/run", {
        method: "POST",
        body: JSON.stringify(opts ?? {}),
      }),

    runStatus: () => request<PipelineRunState>("/pipeline/run-status"),

    // Abort an in-progress run. Backend endpoint to be implemented; the
    // frontend calls POST /pipeline/abort and then refreshes run-status.
    abort: () =>
      request<{ status: string }>("/pipeline/abort", { method: "POST" }),

    // Start the outreach pipeline on a specific set of already-saved leads
    // (the hero-chat "approve these startups" bridge, Task 10).
    runForLeads: (leadIds: string[]) =>
      request<{ status: string; leads: number }>("/pipeline/run-for-leads", {
        method: "POST",
        body: JSON.stringify({ lead_ids: leadIds }),
      }),

    uploadCsv: async (file: File) => {
      // multipart upload — don't set Content-Type, the browser sets the boundary
      const form = new FormData();
      form.append("file", file);
      const headers: Record<string, string> = {};
      if (getAuthToken) {
        const token = await getAuthToken();
        if (token) headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(`${BASE}/pipeline/upload-csv`, {
        method: "POST",
        headers,
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Upload failed: ${res.status}`);
      }
      return res.json() as Promise<{ status: string; filename: string }>;
    },

    scrape: (sources?: string[]) =>
      request<{ results: Record<string, string> }>("/pipeline/scrape", {
        method: "POST",
        body: sources ? JSON.stringify(sources) : undefined,
      }),

    findEmails: () =>
      request<{ status: string }>("/pipeline/find-emails", { method: "POST" }),

    tailorResumes: () =>
      request<{ status: string }>("/pipeline/tailor-resumes", { method: "POST" }),

    draftOutreach: () =>
      request<{ status: string }>("/pipeline/draft-outreach", { method: "POST" }),

    feedGraph: () =>
      request<{ status: string; leads_fed: number }>("/pipeline/feed-graph", { method: "POST" }),

    send: () =>
      request<{
        status: string;
        mode: "direct" | "drafts";
        summary: {
          sent: number;
          draft_created: number;
          skipped_no_email: number;
          skipped_no_draft: number;
          failed: number;
          skipped_quota: number;
          quota_limit?: number;
          total: number;
          error: string | null;
        };
      }>("/pipeline/send", { method: "POST" }),

    checkFollowups: () =>
      request<{ status: string; followups_queued: number }>("/pipeline/check-followups", { method: "POST" }),
  },

  settings: {
    getSearchCriteria: () => request<SearchCriteria>("/settings/search-criteria"),

    updateSearchCriteria: (data: Partial<SearchCriteria>) =>
      request<{ status: string }>("/settings/search-criteria", {
        method: "PUT",
        body: JSON.stringify(data),
      }),

    autoFillFromResume: () =>
      request<SearchCriteria>("/settings/auto-fill-from-resume", { method: "POST" }),

    getPipelineConfig: () => request<PipelineConfig>("/settings/pipeline-config"),

    updatePipelineConfig: (data: Partial<PipelineConfig>) =>
      request<{ status: string }>("/settings/pipeline-config", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },

  health: () => request<{ status: string }>("/health"),

  // -------------------------------------------------------------------------
  // Account conversion (Phase 3.4/3.6) + Profile (Phase 3.7)
  // -------------------------------------------------------------------------

  anon: {
    // Anonymous pre-signup resume upload: parse -> infer criteria -> match
    // the shared catalog, all in one response. No auth header attempted
    // here (getAuthToken is unset/returns null pre-signin, but this is
    // explicit rather than relying on that) -- this route is deliberately
    // reachable without an account.
    uploadResume: async (file: File): Promise<AnonResumeUploadResult> => {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${BASE}/anon/resume`, { method: "POST", body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Upload failed: ${res.status}`);
      }
      return res.json();
    },
  },

  account: {
    convertAnonSession: (parsed_resume: object, inferred_criteria: object) =>
      request<{ resume_id: string; search_criteria_id: string }>(
        "/account/convert-anon-session",
        {
          method: "POST",
          body: JSON.stringify({ parsed_resume, inferred_criteria }),
        }
      ),
  },

  resume: {
    // The user's current base (primary) resume for the Resume page editor.
    base: () => request<BaseResume>("/resume/base"),

    rephrase: (body: {
      jd_text: string;
      company?: string;
      role?: string;
      template?: ResumeTemplate;
      current_tailored_json?: Record<string, unknown>;
    }) =>
      request<RephraseResult>("/resume/rephrase", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    // History of every tailored version we've built (with company + ATS score).
    tailored: () => request<TailoredResumeItem[]>("/resume/tailored"),

    // Render a resume (the on-screen edited version, or the base if omitted)
    // to a PDF and return a blob: URL the caller opens/downloads. Caller is
    // responsible for URL.revokeObjectURL(...) when done.
    downloadPdfBlobUrl: async (body: {
      resume_json?: Record<string, unknown>;
      template?: ResumeTemplate;
      filename?: string;
    }) => {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (getAuthToken) {
        const token = await getAuthToken();
        if (token) headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(`${BASE}/resume/download`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Failed to render PDF: ${res.status}`);
      }
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    },
  },

  /** Max JD characters accepted by the tailoring engine (mirrors backend
   *  MAX_JD_CHARS). Longer input is clipped server-side to avoid diluting the
   *  signal / hallucination. */
  RESUME_MAX_JD_CHARS: 12000,

  profile: {
    getSearchCriteria: () =>
      request<ProfileSearchCriteria>("/profile/search-criteria"),

    updateSearchCriteria: (data: Partial<ProfileSearchCriteria>) =>
      request<ProfileSearchCriteria>("/profile/search-criteria", {
        method: "PUT",
        body: JSON.stringify(data),
      }),

    getResumes: () => request<ProfileResume[]>("/profile/resumes"),

    // Save an edited/tailored resume JSON as a named, re-selectable version
    // (non-primary — the base resume stays the tailoring source of truth).
    saveResume: (body: { parsed_json: Record<string, unknown>; name?: string; is_primary?: boolean }) =>
      request<ProfileResume>("/profile/resumes", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    uploadResume: (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return request<ProfileResume>("/profile/upload-resume", {
        method: "POST",
        body: formData,
      });
    },
  },
};
