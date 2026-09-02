"use client";

import { useState, Suspense } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api, ApiError } from "@/lib/api";
import { Mail, Loader2, CheckCircle2 } from "lucide-react";

function ForgotPasswordForm() {
  const { clearError } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    clearError();
    setLoading(true);
    try {
      await api.forgotPassword(email);
      setSent(true);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : "Failed to send reset email";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  if (sent) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center p-margin-mobile">
        <div className="w-full max-w-md text-center">
          <div className="bg-surface-container-lowest rounded-xl p-8 border border-outline-variant/50">
            <CheckCircle2 className="w-12 h-12 text-primary mx-auto mb-4" />
            <h1 className="font-headline-md text-headline-md text-on-surface mb-2">Check your inbox</h1>
            <p className="font-body-md text-body-md text-on-surface-variant mb-6">
              If that email is registered, we sent a password reset link. Click it to set a new password.
            </p>
            <Link href="/login" className="text-primary font-body-md text-body-md hover:underline">
              Back to login
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center p-margin-mobile">
      <div className="w-full max-w-md">
        <div className="text-center mb-stack-lg">
          <Link href="/" className="font-headline-lg text-headline-lg text-primary">
            Oxiverse Audio
          </Link>
          <p className="font-body-md text-body-md text-on-surface-variant mt-2">Reset your password.</p>
        </div>

        <div className="bg-surface-container-lowest rounded-xl p-8 border border-outline-variant/50">
          <h1 className="font-headline-md text-headline-md text-on-surface mb-6">Forgot password</h1>

          {error && (
            <div className="bg-error-container text-on-error-container font-body-md text-body-md p-3 rounded-lg mb-4">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="font-label-sm text-label-sm text-on-surface-variant block mb-1">Email</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-on-surface-variant" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="founder@startup.com"
                  className="w-full pl-10 pr-4 py-2.5 rounded-lg border border-outline-variant bg-surface font-body-md text-body-md text-on-surface focus:border-primary focus:outline-none"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary text-on-primary font-body-md text-body-md py-2.5 rounded-lg hover:bg-on-primary-fixed transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              Send reset link
            </button>
          </form>

          <p className="font-body-md text-body-md text-on-surface-variant text-center mt-6">
            Remember your password?{" "}
            <Link href="/login" className="text-primary hover:underline">Log in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-surface flex items-center justify-center"><Loader2 className="w-8 h-8 text-primary animate-spin" /></div>}>
      <ForgotPasswordForm />
    </Suspense>
  );
}
