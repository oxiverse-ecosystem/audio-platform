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

  setToken,
  getToken,
  API_BASE,
};

export { ApiError };
