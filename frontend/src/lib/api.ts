/**
 * API client for the AutoApply backend.
 *
 * In development, Next.js rewrites /api/* to localhost:8000/api/*
 * via next.config.js, so we just use relative paths.
 */

const BASE = "/api";

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
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
  lead_id: string;
  company: string;
  demo_title: string;
  running: boolean;
  stage: DemoBuildStage;
  deploy_stage: DemoDeployStage | null;
  attempt: number;
  max_attempts: number;
  started_at: string;
  frontend_url: string | null;
  backend_url: string | null;
}

// ---------------------------------------------------------------------------
// Leads
// ---------------------------------------------------------------------------

export const api = {
  leads: {
    list: (status?: string) =>
      request<Lead[]>(status ? `/leads?status=${status}` : "/leads"),

    get: (id: string) => request<Lead>(`/leads/${id}`),

    approve: (id: string) =>
      request<{ status: string }>(`/leads/${id}/approve`, { method: "POST" }),

    reject: (id: string) =>
      request<{ status: string }>(`/leads/${id}/reject`, { method: "POST" }),

    edit: (id: string, outreach_draft: string) =>
      request<{ status: string }>(`/leads/${id}/edit`, {
        method: "POST",
        body: JSON.stringify({ outreach_draft }),
      }),

    research: (id: string) =>
      request<CompanyResearch>(`/leads/${id}/research`, { method: "POST" }),

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
    list: () => request<DemoBuildSummary[]>("/builds"),
  },

  stats: {
    get: () => request<Stats>("/stats"),
  },

  pipeline: {
    // On-demand full pipeline run (the "Run Pipeline" button)
    run: (opts?: RunPipelineOptions) =>
      request<{ status: string; sources: string[] }>("/pipeline/run", {
        method: "POST",
        body: JSON.stringify(opts ?? {}),
      }),

    runStatus: () => request<PipelineRunState>("/pipeline/run-status"),

    uploadCsv: async (file: File) => {
      // multipart upload — don't set Content-Type, the browser sets the boundary
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${BASE}/pipeline/upload-csv`, {
        method: "POST",
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

    getPipelineConfig: () => request<PipelineConfig>("/settings/pipeline-config"),

    updatePipelineConfig: (data: Partial<PipelineConfig>) =>
      request<{ status: string }>("/settings/pipeline-config", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },

  health: () => request<{ status: string }>("/health"),
};
