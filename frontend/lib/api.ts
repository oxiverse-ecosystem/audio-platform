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
}

export interface JobStatusResponse {
  job_id: string;
  asset_id: string;
  title: string;
  status: string;
  created_at: number;
  updated_at: number;
  report: Record<string, unknown> | null;
  error: string | null;
  download: Record<string, string> | null;
}

export interface EpisodeResponse {
  episode_id: string;
  asset_id: string;
  creator_id: string;
  title: string;
  description: string | null;
  category: string;
  visibility: string;
  duration_seconds: number;
  play_count: number;
  created_at: number;
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

  upload: (file: File, title: string, outputFormat: string, onProgress?: (pct: number) => void) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title);
    formData.append("output_format", outputFormat);

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

  createEpisode: (data: { asset_id: string; title: string; description?: string; category?: string; visibility?: string }) =>
    request<EpisodeResponse>("/v1/episodes", {
      method: "POST",
      body: JSON.stringify(data),
    }, true),

  setToken,
  getToken,
  API_BASE,
};

export { ApiError };
