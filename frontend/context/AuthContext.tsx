"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  ReactNode,
} from "react";
import { api, ApiUser, ApiError } from "@/lib/api";

interface AuthState {
  user: ApiUser | null;
  loading: boolean;
  error: string | null;
  signup: (email: string, display_name: string, password: string, is_creator: boolean) => Promise<{ verify_url: string; verify_token: string; email_sent: boolean }>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  verifyEmail: (token: string) => Promise<void>;
  refresh: () => Promise<void>;
  clearError: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => setError(null), []);

  const refresh = useCallback(async () => {
    if (!api.getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api.me();
      setUser(me);
    } catch (e) {
      api.setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signup = useCallback(async (email: string, display_name: string, password: string, is_creator: boolean) => {
    setError(null);
    try {
      const res = await api.signup(email, display_name, password, is_creator);
      return { verify_url: res.verify_url, verify_token: res.verify_token, email_sent: res.email_sent };
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Signup failed";
      setError(msg);
      throw e;
    }
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setError(null);
    try {
      const res = await api.login(email, password);
      api.setToken(res.access_token);
      setUser({
        user_id: res.user_id,
        email,
        display_name: res.display_name,
        email_verified: res.email_verified,
        is_creator: res.is_creator,
      });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Login failed";
      setError(msg);
      throw e;
    }
  }, []);

  const logout = useCallback(() => {
    api.setToken(null);
    setUser(null);
  }, []);

  const verifyEmail = useCallback(async (token: string) => {
    setError(null);
    try {
      await api.verifyEmail(token);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Verification failed";
      setError(msg);
      throw e;
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, error, signup, login, logout, verifyEmail, refresh, clearError }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
