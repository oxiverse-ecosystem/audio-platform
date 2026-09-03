"use client";

import { useEffect, useRef, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { Player } from "@/components/Player";
import { api, EpisodeResponse } from "@/lib/api";
import {
  Sparkles,
  Gauge,
  Rewind,
  Pause,
  FastForward,
  Volume2,
  ShieldCheck,
  Loader2,
  Mic2,
} from "lucide-react";

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function NowPlayingContent() {
  const params = useSearchParams();
  const [episode, setEpisode] = useState<EpisodeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  const episodeId = params.get("id");

  useEffect(() => {
    if (!episodeId) {
      setLoading(false);
      return;
    }
    api.getEpisode(episodeId)
      .then(setEpisode)
      .catch(() => setEpisode(null))
      .finally(() => setLoading(false));
  }, [episodeId]);

  // Generate waveform bars
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const numBars = Math.max(20, Math.floor(container.clientWidth / 6));
    container.innerHTML = "";
    for (let i = 0; i < numBars; i++) {
      const bar = document.createElement("div");
      bar.className = "waveform-bar";
      const height = Math.floor(Math.random() * 90) + 10;
      bar.style.height = `${height}%`;
      if (i < numBars * 0.3) bar.classList.add("active");
      container.appendChild(bar);
    }
  }, [episode]);

  if (loading) {
    return (
      <div className="flex min-h-screen bg-surface items-center justify-center">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  if (!episode) {
    return (
      <div className="flex min-h-screen bg-surface">
        <Sidebar />
        <main className="flex-1 md:pl-sidebar p-margin-mobile md:p-margin-desktop flex items-center justify-center">
          <div className="text-center">
            <Mic2 className="w-12 h-12 text-on-surface-variant mx-auto mb-4" strokeWidth={1.5} />
            <h2 className="font-headline-md text-headline-md text-on-surface mb-2">Episode not found</h2>
            <p className="font-body-md text-body-md text-on-surface-variant">This episode doesn&apos;t exist or has been removed.</p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 md:pl-sidebar p-margin-mobile md:p-margin-desktop flex flex-col xl:flex-row gap-gutter">
        {/* Player column */}
        <div className="flex-1 flex flex-col gap-stack-lg max-w-4xl">
          <header className="flex justify-between items-start">
            <div>
              <h2 className="font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface">
                {episode.title}
              </h2>
              <p className="font-body-lg text-body-lg text-on-surface-variant mt-2">
                By {episode.creator_id.slice(0, 12)}
              </p>
              <div className="mt-4 inline-flex items-center gap-2 bg-surface-container px-3 py-1.5 rounded-full border border-outline-variant">
                <Sparkles className="text-primary w-4 h-4" strokeWidth={1.5} />
                <span className="font-label-sm text-label-sm text-primary">Enhanced to Studio Quality</span>
              </div>
            </div>
            <div className="hidden sm:flex flex-col items-end bg-surface-container-low p-3 rounded-lg border border-outline-variant shadow-sm">
              <span className="font-label-sm text-label-sm text-on-surface-variant mb-1">Audio Processing Quota</span>
              <div className="w-32 h-2 bg-surface-variant rounded-full overflow-hidden">
                <div className="h-full bg-primary w-[65%]" />
              </div>
              <span className="font-caption text-caption text-on-surface-variant mt-1">65% Used (12h remaining)</span>
            </div>
          </header>

          <section className="bg-surface-container-lowest rounded-xl border border-outline-variant p-stack-lg shadow-sm">
            <div className="w-full h-48 sm:h-64 rounded-lg bg-surface-variant mb-stack-lg overflow-hidden relative flex items-center justify-center">
              <Mic2 className="w-16 h-16 text-on-surface-variant" strokeWidth={1} />
              <div className="absolute inset-0 bg-gradient-to-t from-surface/80 to-transparent" />
            </div>

            {/* Waveform */}
            <div ref={containerRef} className="w-full h-32 flex items-center justify-between mb-stack-md" />

            <div className="flex justify-between font-label-sm text-label-sm text-on-surface-variant mb-stack-lg">
              <span>0:00</span>
              <span>{formatDuration(episode.duration_seconds)}</span>
            </div>

            <div className="flex items-center justify-center gap-6 sm:gap-12">
              <button className="text-on-surface-variant hover:text-primary transition-colors flex flex-col items-center gap-1">
                <Gauge className="w-6 h-6" strokeWidth={1.5} />
                <span className="font-label-sm text-label-sm">1.5x</span>
              </button>
              <button className="text-on-surface-variant hover:text-primary transition-colors flex flex-col items-center gap-1">
                <Rewind className="w-10 h-10" strokeWidth={1.5} />
              </button>
              <button className="w-20 h-20 bg-primary rounded-full flex items-center justify-center text-on-primary hover:bg-primary-container transition-colors shadow-sm">
                <Pause className="w-10 h-10" strokeWidth={1.5} />
              </button>
              <button className="text-on-surface hover:text-primary transition-colors">
                <FastForward className="w-10 h-10" strokeWidth={1.5} />
              </button>
              <button className="text-on-surface-variant hover:text-primary transition-colors flex flex-col items-center gap-1">
                <Volume2 className="w-6 h-6" strokeWidth={1.5} />
              </button>
            </div>
          </section>
        </div>

        {/* Right column */}
        <aside className="w-full xl:w-80 flex flex-col gap-stack-lg">
          <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6 shadow-sm">
            <h3 className="font-headline-md text-headline-md text-on-surface mb-4">Episode Notes</h3>
            <p className="font-body-md text-body-md text-on-surface-variant mb-4">
              {episode.description || "No description provided."}
            </p>
            <div className="flex flex-wrap gap-2">
              <span className="bg-surface-container px-2 py-1 rounded font-label-sm text-label-sm text-on-surface-variant">
                {episode.category}
              </span>
              <span className="bg-surface-container px-2 py-1 rounded font-label-sm text-label-sm text-on-surface-variant">
                {formatDuration(episode.duration_seconds)}
              </span>
              <span className="bg-surface-container px-2 py-1 rounded font-label-sm text-label-sm text-on-surface-variant">
                {episode.play_count} plays
              </span>
            </div>
          </div>

          <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6 shadow-sm flex-1">
            <h3 className="font-headline-md text-headline-md text-on-surface mb-4">Details</h3>
            <ul className="space-y-4">
              <li className="flex gap-4">
                <span className="font-label-sm text-label-sm text-on-surface-variant mt-1">Episode ID</span>
                <div>
                  <p className="font-body-md text-body-md text-on-surface">{episode.episode_id}</p>
                </div>
              </li>
              <li className="flex gap-4">
                <span className="font-label-sm text-label-sm text-on-surface-variant mt-1">Category</span>
                <div>
                  <p className="font-body-md text-body-md text-on-surface">{episode.category}</p>
                </div>
              </li>
              <li className="flex gap-4">
                <span className="font-label-sm text-label-sm text-on-surface-variant mt-1">Visibility</span>
                <div>
                  <p className="font-body-md text-body-md text-on-surface capitalize">{episode.visibility}</p>
                </div>
              </li>
            </ul>
          </div>
          <p className="font-caption text-caption text-on-surface-variant/70 text-center flex items-center justify-center gap-2">
            <ShieldCheck className="w-4 h-4" strokeWidth={1.5} />
            This stream is forensically watermarked for your security.
          </p>
        </aside>
      </main>
      <Player />
    </div>
  );
}

export default function NowPlayingPage() {
  return (
    <Suspense fallback={<div className="flex min-h-screen bg-surface items-center justify-center"><Loader2 className="w-8 h-8 text-primary animate-spin" /></div>}>
      <NowPlayingContent />
    </Suspense>
  );
}
