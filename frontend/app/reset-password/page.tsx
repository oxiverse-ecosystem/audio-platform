"use client";

import { useState, useEffect, useRef, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { ThemeToggle } from "@/components/ThemeToggle";

function ResetPasswordForm() {
  const params = useSearchParams();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const ran = useRef(false);

  const token = params.get("token");

  useEffect(() => {
    if (!token || ran.current) return;
    ran.current = true;
    // Token is in URL — nothing to do yet, user enters new password
  }, [token]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (!token) {
      setError("Missing reset token. Please request a new reset link.");
      return;
    }
    setLoading(true);
    try {
      await api.resetPassword(token, password);
      setSuccess(true);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : "Reset failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center p-margin-mobile relative">
        <div className="absolute top-6 right-6">
          <ThemeToggle />
        </div>
        <div className="w-full max-w-md text-center">
          <div className="bg-surface-container-lowest rounded-xl p-8 border border-outline-variant/50">
            <XCircle className="w-12 h-12 text-error mx-auto mb-4" />
            <h1 className="font-headline-md text-headline-md text-on-surface mb-2">Invalid reset link</h1>
            <p className="font-body-md text-body-md text-on-surface-variant mb-6">
              This password reset link is invalid or missing. Please request a new one.
            </p>
            <Link href="/forgot-password" className="text-primary font-body-md text-body-md hover:underline">
              Request new reset link
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (success) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center p-margin-mobile relative">
        <div className="absolute top-6 right-6">
          <ThemeToggle />
        </div>
        <div className="w-full max-w-md text-center">
          <div className="bg-surface-container-lowest rounded-xl p-8 border border-outline-variant/50">
            <CheckCircle2 className="w-12 h-12 text-primary mx-auto mb-4" />
            <h1 className="font-headline-md text-headline-md text-on-surface mb-2">Password reset</h1>
            <p className="font-body-md text-body-md text-on-surface-variant mb-6">
              Your password has been updated. You can now log in with your new password.
            </p>
            <Link href="/login" className="text-primary font-body-md text-body-md hover:underline">
              Continue to login
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center p-margin-mobile relative">
      <div className="absolute top-6 right-6">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-md">
        <div className="text-center mb-stack-lg">
          <Link href="/" className="font-headline-lg text-headline-lg text-primary">
            Oxiverse Audio
          </Link>
          <p className="font-body-md text-body-md text-on-surface-variant mt-2">Set a new password.</p>
        </div>

        <div className="bg-surface-container-lowest rounded-xl p-8 border border-outline-variant/50">
          <h1 className="font-headline-md text-headline-md text-on-surface mb-6">Reset password</h1>

          {error && (
            <div className="bg-error-container text-on-error-container font-body-md text-body-md p-3 rounded-lg mb-4">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="font-label-sm text-label-sm text-on-surface-variant block mb-1">New password</label>
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Min 8 characters"
                className="w-full px-4 py-2.5 rounded-lg border border-outline-variant bg-surface font-body-md text-body-md text-on-surface focus:border-primary focus:outline-none"
              />
            </div>
            <div>
              <label className="font-label-sm text-label-sm text-on-surface-variant block mb-1">Confirm new password</label>
              <input
                type="password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Repeat password"
                className="w-full px-4 py-2.5 rounded-lg border border-outline-variant bg-surface font-body-md text-body-md text-on-surface focus:border-primary focus:outline-none"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary text-on-primary font-body-md text-body-md py-2.5 rounded-lg hover:bg-on-primary-fixed transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              Reset password
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-surface flex items-center justify-center"><Loader2 className="w-8 h-8 text-primary animate-spin" /></div>}>
      <ResetPasswordForm />
    </Suspense>
  );
}
