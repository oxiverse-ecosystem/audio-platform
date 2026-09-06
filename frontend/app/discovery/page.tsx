"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Search, Clock, Play, Bolt, Loader2, Mic2 } from "lucide-react";
import { Sidebar } from "@/components/Sidebar";
import { Player } from "@/components/Player";
import { useAuth } from "@/context/AuthContext";
import { api, EpisodeResponse } from "@/lib/api";

const DEFAULT_CATEGORIES = ["All", "Tech", "Business", "Founder Stories", "Science", "Product"];

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatPlays(count: number): string {
  if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
  return String(count);
}

function timeAgo(ts: number): string {
  const diff = Date.now() / 1000 - ts;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatHours(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export default function DiscoveryPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [episodes, setEpisodes] = useState<EpisodeResponse[]>([]);
  const [myEpisodes, setMyEpisodes] = useState<EpisodeResponse[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [analytics, setAnalytics] = useState<{ total_episodes: number; total_plays: number; total_duration_seconds: number } | null>(null);

  const fetchEpisodes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getEpisodes({
        category: category === "All" ? undefined : category,
        search: search.trim() || undefined,
      });
      setEpisodes(res.episodes);
    } catch {
      setEpisodes([]);
    } finally {
      setLoading(false);
    }
  }, [category, search]);

  useEffect(() => {
    fetchEpisodes();
  }, [fetchEpisodes]);

  useEffect(() => {
    setMyEpisodes(null);
    setAnalytics(null);
    api.getMyAnalytics()
      .then(setAnalytics)
      .catch(() => setAnalytics(null));
    api.getMyEpisodes()
      .then((r) => setMyEpisodes(r.episodes))
      .catch(() => setMyEpisodes(null));
  }, [user]);

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 flex flex-col md:flex-row min-w-0 overflow-hidden md:pl-sidebar pt-14 md:pt-0">
        {/* Center Canvas */}
        <div className="flex-1 overflow-y-auto px-margin-mobile md:px-margin-desktop py-stack-lg pb-24 hide-scrollbar">
          <div className="max-w-container-max mx-auto mb-stack-lg space-y-stack-lg">
            {user && (
              <div className="bg-surface-container-lowest rounded-2xl border border-outline-variant/40 shadow-sm overflow-hidden">
                <div className="p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div>
                    <p className="font-caption text-caption uppercase tracking-wider text-on-surface-variant mb-1">
                      Welcome{user.display_name ? `, ${user.display_name}` : " back"}
                    </p>
                    <h2 className="font-headline-md text-headline-md text-on-surface font-bold">Your Studio</h2>
                  </div>
                  <div className="flex gap-3">
                    <Link
                      href="/new-drop"
                      className="inline-flex items-center gap-2 bg-primary text-on-primary font-label-sm text-label-sm px-4 py-2 rounded-lg hover:bg-primary-container transition-colors"
                    >
                      <Mic2 className="w-4 h-4" strokeWidth={1.5} />
                      Publish a drop
                    </Link>
                    <Link
                      href="/creator"
                      className="inline-flex items-center gap-2 bg-surface-container text-on-surface font-label-sm text-label-sm px-4 py-2 rounded-lg hover:bg-surface-container-high transition-colors"
                    >
                      <Bolt className="w-4 h-4" strokeWidth={1.5} />
                      Creator studio
                    </Link>
                  </div>
                </div>
                <div className="grid grid-cols-3 divide-x divide-outline-variant/30 border-t border-outline-variant/40">
                  <div className="p-4 sm:p-5">
                    <p className="font-label-sm text-label-sm text-on-surface-variant">Episodes</p>
                    <p className="font-headline-md text-headline-md text-on-surface font-bold mt-1">{myEpisodes?.length ?? analytics?.total_episodes ?? 0}</p>
                  </div>
                  <div className="p-4 sm:p-5">
                    <p className="font-label-sm text-label-sm text-on-surface-variant">Hours published</p>
                    <p className="font-headline-md text-headline-md text-on-surface font-bold mt-1">{formatHours(analytics?.total_duration_seconds ?? 0)}</p>
                  </div>
                  <div className="p-4 sm:p-5">
                    <p className="font-label-sm text-label-sm text-on-surface-variant">Total plays</p>
                    <p className="font-headline-md text-headline-md text-on-surface font-bold mt-1">{formatPlays(analytics?.total_plays ?? 0)}</p>
                  </div>
                </div>
              </div>
            )}

            {user && myEpisodes && myEpisodes.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-stack-md">
                  <h3 className="font-caption text-caption font-bold text-on-surface">Your Episodes</h3>
                  <button
                    onClick={() => router.push("/creator")}
                    className="font-label-sm text-label-sm text-primary hover:text-on-primary-fixed transition-colors"
                  >
                    View all →
                  </button>
                </div>
                <div className="flex gap-gutter overflow-x-auto pb-2 -mx-1 px-1 hide-scrollbar">
                  {myEpisodes.map((ep) => (
                    <MiniEpisodeCard key={ep.episode_id} ep={ep} onPlay={() => router.push(`/now-playing?id=${ep.episode_id}`)} />
                  ))}
                </div>
              </div>
            )}

            {user && myEpisodes && myEpisodes.length === 0 && (
              <div className="bg-surface-container-lowest rounded-xl border border-outline-variant/40 p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 shadow-sm">
                <div>
                  <p className="font-caption text-caption font-bold text-on-surface">No drops yet</p>
                  <p className="font-label-sm text-label-sm text-on-surface-variant mt-1">Publish your first founder story — it will appear right here and in the feed.</p>
                </div>
                <button
                  onClick={() => router.push("/new-drop")}
                  className="shrink-0 inline-flex items-center gap-2 bg-primary text-on-primary font-label-sm text-label-sm px-4 py-2 rounded-lg hover:bg-primary-container transition-colors"
                >
                  <Mic2 className="w-4 h-4" strokeWidth={1.5} />
                  Publish a drop
                </button>
              </div>
            )}

            {/* Discover header */}
            <div className="pt-stack-md">
              <h2 className="font-headline-lg-mobile md:font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface mb-stack-md">
                Discover
              </h2>
            </div>

            {/* Search */}
            <div className="relative w-full max-w-2xl">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-outline w-5 h-5" strokeWidth={1.5} />
              <input
                className="w-full bg-surface-container-lowest border border-outline-variant/50 rounded-xl py-3 pl-12 pr-4 font-label-sm text-label-sm text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all shadow-sm"
                placeholder="Search episodes, creators, or topics..."
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && fetchEpisodes()}
              />
            </div>

            {/* Filter pills */}
            <div className="flex flex-wrap gap-2 mt-stack-md">
              {DEFAULT_CATEGORIES.map((c) => (
                <button
                  key={c}
                  onClick={() => setCategory(c)}
                  className={`px-4 py-1.5 rounded-full font-label-sm text-label-sm transition-colors ${
                    category === c
                      ? "bg-primary text-on-primary"
                      : "bg-surface-container border border-outline-variant/30 text-on-surface hover:bg-surface-container-high"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>

          {/* Episode grid */}
          <div className="max-w-container-max mx-auto">
            {loading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="w-8 h-8 text-primary animate-spin" />
              </div>
            ) : episodes.length === 0 ? (
              <div className="text-center py-20">
                <Mic2 className="w-12 h-12 text-on-surface-variant mx-auto mb-4" strokeWidth={1.5} />
                <h3 className="font-headline-md text-headline-md text-on-surface mb-2">No episodes yet</h3>
                <p className="font-body-md text-body-md text-on-surface-variant mb-6">
                  {search
                    ? "No episodes match your search."
                    : "Be the first founder to share your signal."}
                </p>
                <button
                  onClick={() => router.push("/new-drop")}
                  className="bg-primary text-on-primary font-body-md text-body-md px-6 py-2.5 rounded-lg hover:bg-on-primary-fixed transition-colors"
                >
                  Publish your first episode
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-gutter">
                {episodes.map((ep) => (
                  <EpisodeCard key={ep.episode_id} ep={ep} onPlay={() => router.push(`/now-playing?id=${ep.episode_id}`)} />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Sidebar */}
        <aside className="hidden xl:block w-80 bg-surface-container border-l border-outline-variant/30 p-margin-desktop overflow-y-auto">
          <div className="bg-surface-container-lowest rounded-xl border border-outline-variant/40 p-5 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-caption text-caption font-bold text-on-surface">Your Free Tier</h3>
              <Bolt className="text-outline w-[18px] h-[18px]" strokeWidth={1.5} />
            </div>
            <p className="font-label-sm text-label-sm text-on-surface-variant mb-2">Usage this month</p>
            <div className="w-full bg-surface-container-high rounded-full h-1.5 mb-3">
              <div className="bg-primary h-1.5 rounded-full" style={{ width: analytics ? `${Math.min(100, (analytics.total_duration_seconds / 21600) * 100)}%` : "65%"} } />
            </div>
            <p className="font-caption text-caption text-on-surface font-semibold mb-5">
              {analytics ? `${formatHours(21600 - analytics.total_duration_seconds)} left` : "18h 32m left"}
            </p>
            <button className="w-full bg-surface-container-lowest border border-outline-variant hover:border-primary hover:text-primary text-on-surface font-caption text-caption py-2 rounded-lg transition-colors">
              Upgrade Plan
            </button>
          </div>
          <div className="mt-stack-lg">
            <h3 className="font-caption text-caption font-bold text-on-surface mb-4">Up Next</h3>
            <div className="flex flex-col gap-3">
              {episodes.slice(0, 3).map((ep) => (
                <div
                  key={ep.episode_id}
                  className="flex gap-3 items-center group cursor-pointer"
                  onClick={() => router.push(`/now-playing?id=${ep.episode_id}`)}
                >
                  <div className="w-12 h-12 rounded bg-surface-container-high flex-shrink-0 flex items-center justify-center group-hover:bg-secondary-container transition-colors">
                    <Play className="w-4 h-4 text-outline group-hover:text-primary" strokeWidth={1.5} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-caption text-caption text-on-surface truncate">{ep.title}</p>
                    <p className="font-label-sm text-label-sm text-outline truncate">
                      {formatDuration(ep.duration_seconds)} · {formatPlays(ep.play_count)} plays
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </main>
      <Player />
    </div>
  );
}

function MiniEpisodeCard({ ep, onPlay }: { ep: EpisodeResponse; onPlay: () => void }) {
  return (
    <div
      onClick={onPlay}
      className="flex flex-col w-52 shrink-0 bg-surface-container-lowest rounded-xl border border-outline-variant/40 p-4 hover:border-primary-fixed-dim hover:shadow-[0_4px_20px_rgba(96,99,238,0.08)] transition-all group cursor-pointer"
    >
      <div className="flex-1">
        <p className="font-label-sm text-label-sm text-outline mb-1">{timeAgo(ep.created_at)}</p>
        <h4 className="font-body-md text-body-md text-on-surface font-semibold line-clamp-2 leading-snug">{ep.title}</h4>
      </div>
      <div className="mt-3 flex items-center justify-between">
        <span className="font-label-sm text-label-sm text-outline flex items-center gap-1">
          <Clock className="w-3.5 h-3.5" strokeWidth={1.5} /> {formatDuration(ep.duration_seconds)}
        </span>
        <span className="w-8 h-8 rounded-full bg-surface-container-high group-hover:bg-primary group-hover:text-on-primary flex items-center justify-center transition-colors">
          <Play className="w-4 h-4" strokeWidth={1.5} />
        </span>
      </div>
    </div>
  );
}

function EpisodeCard({ ep, onPlay }: { ep: EpisodeResponse; onPlay: () => void }) {
  return (
    <div
      onClick={onPlay}
      className="bg-surface-container-lowest rounded-[16px] border border-outline-variant/40 p-5 hover:border-primary-fixed-dim hover:shadow-[0_4px_20px_rgba(96,99,238,0.08)] transition-all group flex flex-col cursor-pointer relative overflow-hidden"
    >
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-secondary-container flex items-center justify-center">
            <Mic2 className="w-5 h-5 text-on-secondary-container" strokeWidth={1.5} />
          </div>
          <div>
            <p className="font-caption text-caption text-on-surface font-semibold">{ep.creator_id.slice(0, 12)}</p>
            <p className="font-label-sm text-label-sm text-outline text-[10px]">{timeAgo(ep.created_at)}</p>
          </div>
        </div>
      </div>
      <h3 className="font-headline-md text-headline-md font-bold mb-2 leading-tight">{ep.title}</h3>
      {ep.description && (
        <p className="font-body-md text-body-md text-on-surface-variant max-w-md line-clamp-2 mb-2">{ep.description}</p>
      )}
      <div className="mt-auto pt-4 flex items-center justify-between border-t border-outline-variant/20">
        <div className="flex items-center gap-4 text-outline font-label-sm text-label-sm">
          <span className="flex items-center gap-1">
            <Clock className="w-4 h-4" strokeWidth={1.5} /> {formatDuration(ep.duration_seconds)}
          </span>
          <span className="flex items-center gap-1">
            <Play className="w-4 h-4" strokeWidth={1.5} /> {formatPlays(ep.play_count)}
          </span>
        </div>
        <button className="w-8 h-8 rounded-full bg-surface-container-high group-hover:bg-primary group-hover:text-on-primary flex items-center justify-center transition-colors">
          <Play className="w-[18px] h-[18px]" strokeWidth={1.5} />
        </button>
      </div>
    </div>
  );
}
