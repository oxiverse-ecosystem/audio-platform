"use client";

import { useState, Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { Mail, Lock, Eye, EyeOff, Loader2 } from "lucide-react";

function LoginForm() {
  const { login, error, clearError } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const verifyToken = params.get("token");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);
    clearError();
    setLoading(true);
    try {
      await login(email, password);
      router.push("/discovery");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Login failed";
      // If unverified, offer to go to verify page
      if (msg.includes("not verified")) {
        setLocalError("Email not verified. Check your inbox for the verification link, or sign up again to get a new one.");
      } else {
        setLocalError(msg);
      }
    } finally {
      setLoading(false);
    }
  }

  const displayError = localError || error;

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center p-margin-mobile">
      <div className="w-full max-w-md">
        <div className="text-center mb-stack-lg">
          <Link href="/" className="font-headline-lg text-headline-lg text-primary">
            Oxiverse Audio
          </Link>
          <p className="font-body-md text-body-md text-on-surface-variant mt-2">Welcome back, founder.</p>
        </div>

        <div className="bg-surface-container-lowest rounded-xl p-8 border border-outline-variant/50">
          <h1 className="font-headline-md text-headline-md text-on-surface mb-6">Log in</h1>

          {displayError && (
            <div className="bg-error-container text-on-error-container font-body-md text-body-md p-3 rounded-lg mb-4">
              {displayError}
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

            <div>
              <label className="font-label-sm text-label-sm text-on-surface-variant block mb-1">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-on-surface-variant" />
                <input
                  type={showPw ? "text" : "password"}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-10 pr-10 py-2.5 rounded-lg border border-outline-variant bg-surface font-body-md text-body-md text-on-surface focus:border-primary focus:outline-none"
                />
                <button type="button" onClick={() => setShowPw(!showPw)} className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant">
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary text-on-primary font-body-md text-body-md py-2.5 rounded-lg hover:bg-on-primary-fixed transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              Log in
            </button>
          </form>

          <p className="font-body-md text-body-md text-on-surface-variant text-center mt-6">
            No account?{" "}
            <Link href="/signup" className="text-primary hover:underline">Sign up</Link>
          </p>
        </div>

        {verifyToken && (
          <p className="font-label-sm text-label-sm text-on-surface-variant text-center mt-4">
            Verification token detected — log in after verifying.
          </p>
        )}
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-surface flex items-center justify-center"><Loader2 className="w-8 h-8 text-primary animate-spin" /></div>}>
      <LoginForm />
    </Suspense>
  );
}
