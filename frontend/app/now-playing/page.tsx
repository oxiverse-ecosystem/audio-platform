"use client";

import { useEffect, useRef, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { api, EpisodeResponse } from "@/lib/api";
import { useAudioPlayer } from "@/context/AudioPlayerContext";
import {
  Sparkles,
  Gauge,
  Rewind,
  Pause,
  Play,
  FastForward,
  Volume2,
  VolumeX,
  ShieldCheck,
  Loader2,
  Mic2,
} from "lucide-react";

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatHours(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

const SPEEDS = [1, 1.25, 1.5, 2];

function NowPlayingContent() {
  const params = useSearchParams();
  const [episode, setEpisode] = useState<EpisodeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [quota, setQuota] = useState<{ total_duration_seconds: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const {
    episode: activeEpisode,
    isPlaying,
    currentTime,
    duration,
    volume,
    playbackRate,
    loading: playerLoading,
    play,
    togglePlay,
    seek,
    setVolume,
    setPlaybackRate,
  } = useAudioPlayer();

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

  useEffect(() => {
    api.getMyAnalytics()
      .then((d) => setQuota({ total_duration_seconds: d.total_duration_seconds }))
      .catch(() => setQuota(null));
  }, []);

  // Auto-play when episode loads
  useEffect(() => {
    if (episode && episode.episode_id !== activeEpisode?.episode_id) {
      play(episode);
    }
  }, [episode]); // eslint-disable-line react-hooks/exhaustive-deps

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
      // Highlight bars based on progress
      const progress = duration > 0 ? currentTime / duration : 0;
      if (i < numBars * progress) bar.classList.add("active");
      container.appendChild(bar);
    }
  }, [episode, currentTime, duration]);

  // Waveform click to seek
  const handleWaveformClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const container = containerRef.current;
    if (!container || duration <= 0) return;
    const rect = container.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    seek(pct * duration);
  };

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

  const displayDuration = duration || episode.duration_seconds;

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 min-w-0 overflow-x-hidden overflow-y-auto md:pl-sidebar pt-14 md:pt-0 pb-24">
        <div className="p-margin-mobile md:p-margin-desktop flex flex-col xl:flex-row gap-gutter">
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
                <div className="h-full bg-primary" style={{ width: quota ? `${Math.min(100, (quota.total_duration_seconds / 21600) * 100)}%` : "65%" }} />
              </div>
              <span className="font-caption text-caption text-on-surface-variant mt-1">
                {quota ? `${Math.min(100, Math.round((quota.total_duration_seconds / 21600) * 100))}% Used (${formatHours(21600 - quota.total_duration_seconds)} remaining)` : "65% Used (12h remaining)"}
              </span>
            </div>
          </header>

          <section className="bg-surface-container-lowest rounded-xl border border-outline-variant p-stack-lg shadow-sm">
            <div className="w-full h-48 sm:h-64 rounded-lg bg-surface-variant mb-stack-lg overflow-hidden relative flex items-center justify-center">
              <Mic2 className="w-16 h-16 text-on-surface-variant" strokeWidth={1} />
              <div className="absolute inset-0 bg-gradient-to-t from-surface/80 to-transparent" />
            </div>

            {/* Waveform */}
            <div
              ref={containerRef}
              className="w-full h-32 flex items-center justify-between mb-stack-md cursor-pointer"
              onClick={handleWaveformClick}
            />

            <div className="flex justify-between font-label-sm text-label-sm text-on-surface-variant mb-stack-lg">
              <span>{formatDuration(currentTime)}</span>
              <span>{formatDuration(displayDuration)}</span>
            </div>

            <div className="flex items-center justify-center gap-6 sm:gap-12">
              <button
                onClick={() => {
                  const speeds = SPEEDS;
                  const idx = speeds.indexOf(playbackRate);
                  setPlaybackRate(speeds[(idx + 1) % speeds.length]);
                }}
                className="text-on-surface-variant hover:text-primary transition-colors flex flex-col items-center gap-1"
              >
                <Gauge className="w-6 h-6" strokeWidth={1.5} />
                <span className="font-label-sm text-label-sm">{playbackRate}x</span>
              </button>
              <button
                onClick={() => seek(Math.max(0, currentTime - 15))}
                className="text-on-surface hover:text-primary transition-colors"
              >
                <Rewind className="w-10 h-10" strokeWidth={1.5} />
              </button>
              <button
                onClick={togglePlay}
                disabled={playerLoading}
                className="w-20 h-20 bg-primary rounded-full flex items-center justify-center text-on-primary hover:bg-primary-container transition-colors shadow-sm disabled:opacity-50"
              >
                {playerLoading ? (
                  <Loader2 className="w-10 h-10 animate-spin" strokeWidth={1.5} />
                ) : isPlaying ? (
                  <Pause className="w-10 h-10" strokeWidth={1.5} />
                ) : (
                  <Play className="w-10 h-10" strokeWidth={1.5} />
                )}
              </button>
              <button
                onClick={() => seek(Math.min(displayDuration, currentTime + 30))}
                className="text-on-surface hover:text-primary transition-colors"
              >
                <FastForward className="w-10 h-10" strokeWidth={1.5} />
              </button>
              <div className="flex flex-col items-center gap-1">
                <button
                  onClick={() => setVolume(volume > 0 ? 0 : 1)}
                  className="text-on-surface-variant hover:text-primary transition-colors"
                >
                  {volume === 0 ? (
                    <VolumeX className="w-6 h-6" strokeWidth={1.5} />
                  ) : (
                    <Volume2 className="w-6 h-6" strokeWidth={1.5} />
                  )}
                </button>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={volume}
                  onChange={(e) => setVolume(parseFloat(e.target.value))}
                  className="w-16 h-1 accent-primary cursor-pointer"
                />
              </div>
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
                {formatDuration(displayDuration)}
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
            </ul>
          </div>
          <p className="font-caption text-caption text-on-surface-variant/70 text-center flex items-center justify-center gap-2">
            <ShieldCheck className="w-4 h-4" strokeWidth={1.5} />
            This stream is forensically watermarked for your security.
          </p>
        </aside>
        </div>
      </main>
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
