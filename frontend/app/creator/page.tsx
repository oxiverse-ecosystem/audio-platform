"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { useAuth } from "@/context/AuthContext";
import { api, ApiError } from "@/lib/api";
import {
  Headphones,
  User,
  Clock,
  TrendingUp,
  Landmark,
  Loader2,
} from "lucide-react";

interface Analytics {
  total_episodes: number;
  total_plays: number;
  total_duration_seconds: number;
  total_earnings: number;
}

function formatNumber(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function formatHours(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export default function CreatorDashboardPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [stats, setStats] = useState<Analytics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [user, loading, router]);

  useEffect(() => {
    if (!user) return;
    api.getMyAnalytics()
      .then(setStats)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load analytics"));
  }, [user]);

  if (loading) {
    return (
      <div className="flex min-h-screen bg-surface items-center justify-center">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-screen bg-surface items-center justify-center p-margin-mobile">
        <div className="text-center">
          <h1 className="font-headline-md text-headline-md text-on-surface mb-2">Sign in required</h1>
          <p className="font-body-md text-body-md text-on-surface-variant">Log in to view your analytics.</p>
        </div>
      </div>
    );
  }

  const MONTHLY_QUOTA_SECONDS = 21600;

  const STATS = stats
    ? [
        { label: "Total Episodes", value: formatNumber(stats.total_episodes), delta: "Published", icon: Headphones, up: true },
        { label: "Total Plays", value: formatNumber(stats.total_plays), delta: "All time", icon: User, up: true },
        { label: "Total Hours", value: `${Math.round(stats.total_duration_seconds / 3600)}h`, delta: "Content", icon: Clock, up: true },
        { label: "Quota Left", value: formatHours(Math.max(0, MONTHLY_QUOTA_SECONDS - stats.total_duration_seconds)), delta: "Free tier this month", icon: Landmark, up: true },
      ]
    : [];

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 min-w-0 overflow-x-hidden overflow-y-auto md:pl-sidebar pt-14 md:pt-0 pb-24">
        <div className="max-w-container-max mx-auto p-margin-mobile md:p-margin-desktop space-y-stack-lg">
          <header className="flex justify-between items-end pb-stack-md border-b border-outline-variant/50">
            <div>
              <h2 className="font-headline-lg-mobile md:font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface mb-2">
                Creator Studio
              </h2>
              <p className="font-body-md text-body-md text-on-surface-variant">Your studio overview, monthly usage, and growth.</p>
            </div>
            <div className="hidden sm:block">
              <span className="bg-secondary-fixed text-on-secondary-fixed px-3 py-1 rounded-full font-label-sm text-label-sm uppercase">
                {user.is_creator ? "Creator" : "Listener"}
              </span>
            </div>
          </header>

          {error && (
            <div className="bg-error-container text-on-error-container font-body-md text-body-md p-3 rounded-lg">
              {error}
            </div>
          )}

          {/* Stats bento */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-gutter">
            {STATS.map((s) => (
              <div key={s.label} className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm hover:border-primary-fixed-dim transition-colors group">
                <div className="flex justify-between items-start mb-4">
                  <span className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">{s.label}</span>
                  <s.icon className="text-outline w-5 h-5 group-hover:text-primary transition-colors" strokeWidth={1.5} />
                </div>
                <div className="font-display-lg text-display-lg text-on-surface">{s.value}</div>
                <div className={`mt-2 text-sm flex items-center gap-1 ${s.up ? "text-primary" : "text-outline"}`}>
                  <TrendingUp className="w-4 h-4" strokeWidth={1.5} />
                  <span className="font-caption text-caption">{s.delta}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Chart placeholder */}
          <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm">
            <div className="flex justify-between items-center mb-6">
              <h3 className="font-headline-md text-headline-md text-on-surface">Listens Over Time</h3>
              <select className="bg-surface-container-low border-outline-variant/50 text-on-surface text-sm rounded-md py-1 px-3 focus:border-primary focus:ring-primary font-caption">
                <option>Last 7 Days</option>
                <option>Last 30 Days</option>
                <option>All Time</option>
              </select>
            </div>
            <div className="h-64 flex items-center justify-center text-on-surface-variant font-body-md">
              {stats && stats.total_plays > 0
                ? `Chart data: ${stats.total_plays} total plays across ${stats.total_episodes} episodes`
                : "No listening data yet. Publish episodes to see analytics."}
            </div>
          </div>

          {/* Bottom: payout + quota */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-gutter pb-stack-lg">
            <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm flex flex-col justify-between">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Landmark className="text-outline w-5 h-5" strokeWidth={1.5} />
                  <h3 className="font-caption text-caption text-on-surface-variant uppercase tracking-wide">Next Payout</h3>
                </div>
                <div className="font-display-lg text-display-lg text-on-surface">
                  ${stats ? stats.total_earnings.toFixed(2) : "0.00"}
                </div>
                <p className="font-body-md text-body-md text-on-surface-variant mt-1">
                  {stats && stats.total_earnings > 0 ? "Processing" : "No earnings yet"}
                </p>
              </div>
            </div>

            <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm">
              <div className="flex items-center gap-2 mb-4">
                <Clock className="text-outline w-5 h-5" strokeWidth={1.5} />
                <h3 className="font-caption text-caption text-on-surface-variant uppercase tracking-wide">Free Tier Usage</h3>
              </div>
              <div className="flex items-baseline justify-between mb-2">
                <div className="font-display-lg text-display-lg text-on-surface">
                  {stats ? formatHours(Math.max(0, MONTHLY_QUOTA_SECONDS - stats.total_duration_seconds)) : "6h 0m"} left
                </div>
                <span className="font-label-sm text-label-sm text-on-surface-variant">
                  of {formatHours(MONTHLY_QUOTA_SECONDS)} this month
                </span>
              </div>
              <div className="w-full bg-surface-container-high rounded-full h-2 mt-3 overflow-hidden">
                <div
                  className="bg-primary h-2 rounded-full transition-all"
                  style={{ width: stats ? `${Math.min(100, (stats.total_duration_seconds / MONTHLY_QUOTA_SECONDS) * 100)}%` : "0%" }}
                />
              </div>
              <p className="font-caption text-caption text-on-surface-variant mt-4">
                Listening time on any episode counts toward your free monthly quota.
              </p>
              <Link
                href="/account"
                className="mt-5 inline-block w-full text-center px-4 py-2 bg-surface-container text-on-surface rounded-md font-caption text-caption hover:bg-surface-container-high transition-colors"
              >
                Upgrade Plan
              </Link>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
