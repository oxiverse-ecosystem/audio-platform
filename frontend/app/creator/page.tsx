"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { useAuth } from "@/context/AuthContext";
import { api, ApiError } from "@/lib/api";
import {
  Headphones,
  User,
  Banknote,
  CreditCard,
  TrendingUp,
  Landmark,
  Loader2,
} from "lucide-react";

interface Analytics {
  total_episodes: number;
  total_plays: number;
  total_duration_seconds: number;
  total_earnings: number;
  pack_subscribers: number;
}

function formatNumber(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
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

  const STATS = stats
    ? [
        { label: "Total Episodes", value: formatNumber(stats.total_episodes), delta: "Published", icon: Headphones, up: true },
        { label: "Total Plays", value: formatNumber(stats.total_plays), delta: "All time", icon: User, up: true },
        { label: "Total Hours", value: `${Math.round(stats.total_duration_seconds / 3600)}h`, delta: "Content", icon: Banknote, up: true },
        { label: "Pack Subscribers", value: formatNumber(stats.pack_subscribers), delta: "Active", icon: CreditCard, up: true },
      ]
    : [];

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-margin-mobile md:p-margin-desktop md:pl-sidebar">
        <div className="max-w-container-max mx-auto space-y-stack-lg">
          <header className="flex justify-between items-end pb-stack-md border-b border-outline-variant/50">
            <div>
              <h2 className="font-headline-lg-mobile md:font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface mb-2">
                Creator Analytics
              </h2>
              <p className="font-body-md text-body-md text-on-surface-variant">Your pack performance and earnings overview.</p>
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

          {/* Bottom: payout + pricing */}
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

            <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm relative overflow-hidden">
              <h3 className="font-headline-md text-headline-md text-on-surface mb-2 relative z-10">Creator Pack Pricing</h3>
              <p className="font-body-md text-body-md text-on-surface-variant mb-6 relative z-10">
                Adjust the monthly subscription price for your premium audio packs.
              </p>
              <div className="space-y-4 relative z-10">
                <div>
                  <label className="block font-label-sm text-label-sm text-on-surface-variant uppercase mb-1" htmlFor="price">
                    Monthly Price (USD)
                  </label>
                  <div className="relative mt-1 rounded-md shadow-sm">
                    <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                      <span className="text-outline font-body-md">$</span>
                    </div>
                    <input
                      className="block w-full rounded-md border-outline-variant/50 pl-7 py-3 text-on-surface focus:border-primary focus:ring-primary sm:text-sm bg-surface-container-lowest font-body-md font-medium"
                      id="price"
                      name="price"
                      placeholder="9.99"
                      type="number"
                      defaultValue="9.99"
                    />
                  </div>
                  <p className="mt-2 text-sm text-outline font-caption flex items-center gap-1">
                    Suggested range: $5 - $15/mo based on your audience.
                  </p>
                </div>
                <div className="pt-4 border-t border-outline-variant/30 flex justify-end gap-3">
                  <button className="px-4 py-2 bg-surface-container text-on-surface rounded-md font-caption text-caption hover:bg-surface-container-high transition-colors">Cancel</button>
                  <button className="px-4 py-2 bg-primary text-on-primary rounded-md font-caption text-caption hover:bg-primary/90 transition-colors shadow-sm">Save Changes</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
