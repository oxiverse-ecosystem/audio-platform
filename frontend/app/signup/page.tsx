"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { Mail, Lock, User, Eye, EyeOff, Loader2, CheckCircle2 } from "lucide-react";

export default function SignupPage() {
  const { signup, error, clearError } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [isCreator, setIsCreator] = useState(false);
  const [loading, setLoading] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [success, setSuccess] = useState<{ email_sent: boolean; verify_url: string } | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);
    clearError();
    setLoading(true);
    try {
      const res = await signup(email, displayName, password, isCreator);
      setSuccess({ email_sent: res.email_sent, verify_url: res.verify_url });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Signup failed";
      setLocalError(msg);
    } finally {
      setLoading(false);
    }
  }

  if (success) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center p-margin-mobile">
        <div className="w-full max-w-md text-center">
          <div className="bg-surface-container-lowest rounded-xl p-8 border border-outline-variant/50">
            <CheckCircle2 className="w-12 h-12 text-primary mx-auto mb-4" />
            <h1 className="font-headline-md text-headline-md text-on-surface mb-2">Check your inbox</h1>
            <p className="font-body-md text-body-md text-on-surface-variant mb-6">
              {success.email_sent
                ? "We sent a verification link to your email. Click it to activate your account."
                : "Your account was created. Use the link below to verify your email (dev mode — no email sent)."}
            </p>
            <a
              href={success.verify_url}
              className="inline-block bg-primary text-on-primary font-body-md text-body-md px-6 py-2.5 rounded-lg hover:bg-on-primary-fixed transition-colors"
            >
              Verify email now
            </a>
            <p className="font-label-sm text-label-sm text-on-surface-variant mt-4">
              After verifying,{" "}
              <Link href="/login" className="text-primary hover:underline">log in here</Link>.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const displayError = localError || error;

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center p-margin-mobile">
      <div className="w-full max-w-md">
        <div className="text-center mb-stack-lg">
          <Link href="/" className="font-headline-lg text-headline-lg text-primary">
            Oxiverse Audio
          </Link>
          <p className="font-body-md text-body-md text-on-surface-variant mt-2">Create your founder account.</p>
        </div>

        <div className="bg-surface-container-lowest rounded-xl p-8 border border-outline-variant/50">
          <h1 className="font-headline-md text-headline-md text-on-surface mb-6">Sign up</h1>

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
              <label className="font-label-sm text-label-sm text-on-surface-variant block mb-1">Display name</label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-on-surface-variant" />
                <input
                  type="text"
                  required
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Likhith Sai"
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
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min 8 characters"
                  className="w-full pl-10 pr-10 py-2.5 rounded-lg border border-outline-variant bg-surface font-body-md text-body-md text-on-surface focus:border-primary focus:outline-none"
                />
                <button type="button" onClick={() => setShowPw(!showPw)} className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant">
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={isCreator}
                onChange={(e) => setIsCreator(e.target.checked)}
                className="w-4 h-4 rounded border-outline-variant text-primary focus:ring-primary"
              />
              <span className="font-body-md text-body-md text-on-surface-variant">I&apos;m a founder who wants to publish audio</span>
            </label>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary text-on-primary font-body-md text-body-md py-2.5 rounded-lg hover:bg-on-primary-fixed transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              Create account
            </button>
          </form>

          <p className="font-body-md text-body-md text-on-surface-variant text-center mt-6">
            Already have an account?{" "}
            <Link href="/login" className="text-primary hover:underline">Log in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
