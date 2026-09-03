"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Search, Lock, Clock, Play, Bolt, Loader2, Mic2 } from "lucide-react";
import { Sidebar } from "@/components/Sidebar";
import { Player } from "@/components/Player";
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

export default function DiscoveryPage() {
  const router = useRouter();
  const [episodes, setEpisodes] = useState<EpisodeResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");

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

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 flex flex-col md:flex-row min-w-0 overflow-hidden md:pl-sidebar">
        {/* Center Canvas */}
        <div className="flex-1 overflow-y-auto px-margin-mobile md:px-margin-desktop py-stack-lg hide-scrollbar">
          <div className="max-w-container-max mx-auto mb-stack-lg">
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
              <div className="bg-primary h-1.5 rounded-full" style={{ width: "65%" }} />
            </div>
            <p className="font-caption text-caption text-on-surface font-semibold mb-5">18h 32m left</p>
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
        {ep.visibility === "pack" && (
          <span className="bg-surface-container px-2 py-0.5 rounded text-[10px] font-label-sm text-on-surface-variant flex items-center gap-1 border border-outline-variant/20">
            <Lock className="w-3 h-3" strokeWidth={1.5} /> Pack
          </span>
        )}
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
