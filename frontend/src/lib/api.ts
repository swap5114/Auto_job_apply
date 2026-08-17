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

export interface CompanyResearch {
  overview: string;
  stage: string;
  industry: string;
  tech_signals: string[];
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
  sent: number;
  replied: number;
  rejected: number;
}

export interface SearchCriteria {
  role_keywords: string[];
  seniority_exclude_keywords: string[];
  years_experience_threshold: number;
  location_keywords: string[];
}

export interface PipelineConfig {
  model_backend: string;
  followup_days: number;
  max_followups: number;
  gmail_direct_send: boolean;
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
  },

  stats: {
    get: () => request<Stats>("/stats"),
  },

  pipeline: {
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
      request<{ status: string }>("/pipeline/send", { method: "POST" }),

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
