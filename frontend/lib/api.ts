/**
 * Audio Platform API client.
 *
 * Base URL: set NEXT_PUBLIC_API_BASE in your frontend .env.local
 * (defaults to http://localhost:8000 — the FastAPI dev server).
 *
 * Auth: bearer token persisted in localStorage under `ap_token`.
 */

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "ap_token";

export interface ApiUser {
  user_id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
  is_creator: boolean;
  created_at?: number;
}

export interface SignupResponse {
  user_id: string;
  email: string;
  email_verified: boolean;
  email_sent: boolean;
  verify_url: string;
  verify_token: string;
  dev_note: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  display_name: string;
  email_verified: boolean;
  is_creator: boolean;
}

export interface UploadResponse {
  job_id: string;
  asset_id: string;
  status: string;
  status_url: string;
  episode_id?: string | null;
}

export interface JobStatusResponse {
  job_id: string;
  asset_id: string;
  title: string;
  status: string;
  created_at: number;
  updated_at: number;
  report: {
    sample_rate?: number;
    duration_seconds?: number;
    waveform_peaks?: number[];
    repair?: Record<string, unknown>;
    enhance?: Record<string, unknown>;
    [key: string]: unknown;
  } | null;
  error: string | null;
  download: {
    mp3?: string;
    wav?: string;
    raw?: string;
    [key: string]: string | undefined;
  } | null;
}

export interface EpisodeResponse {
  episode_id: string;
  asset_id: string;
  creator_id: string;
  title: string;
  description: string | null;
  category: string;
  visibility: string;
  status: "draft" | "processing" | "ready" | "published";
  publish_on_ready?: number;
  duration_seconds: number;
  play_count: number;
  waveform_peaks?: number[] | null;
  created_at: number;
}

export interface TimeseriesPoint {
  date: string;
  timestamp: number;
  plays: number;
  completed_plays: number;
  completion_rate: number;
  avg_duration_seconds: number;
}

export interface TimeseriesResponse {
  days: number;
  total_plays: number;
  overall_retention_rate: number;
  avg_listen_seconds: number;
  points: TimeseriesPoint[];
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options: RequestInit = {}, auth = false): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    const detail = data?.detail || res.statusText;
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data as T;
}

export const api = {
  signup: (email: string, display_name: string, password: string, is_creator: boolean) =>
    request<SignupResponse>("/v1/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, display_name, password, is_creator }),
    }),

  verifyEmail: (token: string) =>
    request<{ verified: boolean; user_id: string }>("/v1/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  login: (email: string, password: string) =>
    request<LoginResponse>("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () => request<ApiUser>("/v1/auth/me", {}, true),

  upload: (
    file: File,
    title: string,
    outputFormat: string,
    options?: { description?: string; category?: string; publish_immediate?: boolean },
    onProgress?: (pct: number) => void
  ) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title);
    formData.append("output_format", outputFormat);
    if (options?.description) formData.append("description", options.description);
    if (options?.category) formData.append("category", options.category);
    if (options?.publish_immediate) formData.append("publish_immediate", "true");

    return new Promise<UploadResponse>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/v1/uploads`);
      const token = getToken();
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        const data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
        if (xhr.status >= 200 && xhr.status < 300) resolve(data as UploadResponse);
        else reject(new ApiError(xhr.status, data?.detail || xhr.statusText));
      };
      xhr.onerror = () => reject(new ApiError(0, "Upload failed"));
      xhr.send(formData);
    });
  },

  getUploadStatus: (jobId: string) =>
    request<JobStatusResponse>(`/v1/uploads/${jobId}`, {}, true),

  getEpisodes: (params: { category?: string; search?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.category) qs.set("category", params.category);
    if (params.search) qs.set("search", params.search);
    qs.set("limit", String(params.limit ?? 50));
    qs.set("offset", String(params.offset ?? 0));
    return request<{ episodes: EpisodeResponse[]; limit: number; offset: number }>(
      `/v1/episodes?${qs.toString()}`,
    );
  },

  getEpisode: (episodeId: string) =>
    request<EpisodeResponse>(`/v1/episodes/${episodeId}`),

  getDrafts: () =>
    request<{ drafts: EpisodeResponse[] }>("/v1/episodes/drafts", {}, true),

  publishDraft: (episodeId: string) =>
    request<EpisodeResponse>(`/v1/episodes/${episodeId}/publish`, {
      method: "POST",
    }, true),

  createEpisode: (data: { asset_id: string; title: string; description?: string; category?: string }) =>
    request<EpisodeResponse>("/v1/episodes", {
      method: "POST",
      body: JSON.stringify(data),
    }, true),

  recordPlay: (episodeId: string, data: { duration_listened_seconds?: number; completed?: boolean } = {}) =>
    request<{ status: string; play_count: number }>(`/v1/episodes/${episodeId}/play`, {
      method: "POST",
      body: JSON.stringify({
        duration_listened_seconds: data.duration_listened_seconds ?? 0,
        completed: Boolean(data.completed),
      }),
    }),

  getMyAnalytics: () =>
    request<{ total_episodes: number; total_plays: number; total_duration_seconds: number; total_earnings: number; pack_subscribers: number }>(
      "/v1/analytics/me", {}, true,
    ),

  getCreatorTimeseries: (days: number = 30) =>
    request<TimeseriesResponse>(`/v1/analytics/creator/timeseries?days=${days}`, {}, true),

  getMyEpisodes: () =>
    request<{ episodes: EpisodeResponse[] }>("/v1/episodes/me", {}, true),

  forgotPassword: (email: string) =>
    request<{ message: string; email_sent: boolean }>("/v1/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  resetPassword: (token: string, newPassword: string) =>
    request<{ message: string }>("/v1/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password: newPassword }),
    }),

  createStreamSession: (assetId: string) =>
    request<{ session_id: string; expires_at: number }>(
      `/v1/ab/streams/${assetId}/sessions`,
      { method: "POST" },
      true,
    ),

  getStreamPlaylist: async (sessionId: string): Promise<string> => {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}/v1/ab/streams/${sessionId}/playlist.m3u8`, { headers });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    return res.text();
  },

  setToken,
  getToken,
  API_BASE,
};

export { ApiError };
