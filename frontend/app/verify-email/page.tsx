"use client";

import { useEffect, useState, useRef, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";

type Status = "verifying" | "success" | "error";

function VerifyEmailForm() {
  const { verifyEmail, error } = useAuth();
  const params = useSearchParams();
  const [status, setStatus] = useState<Status>("verifying");
  const [message, setMessage] = useState("");
  const ran = useRef(false);

  useEffect(() => {
    const token = params.get("token");
    if (!token || ran.current) return;
    ran.current = true;

    verifyEmail(token)
      .then(() => {
        setStatus("success");
        setMessage("Your email is verified. You can now log in.");
      })
      .catch((err: unknown) => {
        setStatus("error");
        setMessage(err instanceof Error ? err.message : "Verification failed. The link may be expired or already used.");
      });
  }, [params, verifyEmail]);

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center p-margin-mobile">
      <div className="w-full max-w-md text-center">
        <div className="bg-surface-container-lowest rounded-xl p-8 border border-outline-variant/50">
          {status === "verifying" && (
            <>
              <Loader2 className="w-12 h-12 text-primary mx-auto mb-4 animate-spin" />
              <h1 className="font-headline-md text-headline-md text-on-surface mb-2">Verifying your email…</h1>
              <p className="font-body-md text-body-md text-on-surface-variant">One moment.</p>
            </>
          )}

          {status === "success" && (
            <>
              <CheckCircle2 className="w-12 h-12 text-primary mx-auto mb-4" />
              <h1 className="font-headline-md text-headline-md text-on-surface mb-2">Email verified</h1>
              <p className="font-body-md text-body-md text-on-surface-variant mb-6">{message}</p>
              <Link
                href="/login"
                className="inline-block bg-primary text-on-primary font-body-md text-body-md px-6 py-2.5 rounded-lg hover:bg-on-primary-fixed transition-colors"
              >
                Continue to login
              </Link>
            </>
          )}

          {status === "error" && (
            <>
              <XCircle className="w-12 h-12 text-error mx-auto mb-4" />
              <h1 className="font-headline-md text-headline-md text-on-surface mb-2">Verification failed</h1>
              <p className="font-body-md text-body-md text-on-surface-variant mb-6">{message}</p>
              <div className="flex flex-col gap-2">
                <Link
                  href="/signup"
                  className="inline-block bg-primary text-on-primary font-body-md text-body-md px-6 py-2.5 rounded-lg hover:bg-on-primary-fixed transition-colors"
                >
                  Sign up again
                </Link>
                <Link href="/login" className="text-primary font-body-md text-body-md hover:underline">
                  Back to login
                </Link>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-surface flex items-center justify-center"><Loader2 className="w-8 h-8 text-primary animate-spin" /></div>}>
      <VerifyEmailForm />
    </Suspense>
  );
}
