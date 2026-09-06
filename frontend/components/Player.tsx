"use client";

import { useState } from "react";
import Link from "next/link";
import { Play, Pause, Volume2, VolumeX, Mic2 } from "lucide-react";
import { useAudioPlayer } from "@/context/AudioPlayerContext";

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function Player() {
  const { episode, isPlaying, currentTime, duration, volume, togglePlay, seek, setVolume } = useAudioPlayer();
  const [showVolume, setShowVolume] = useState(false);

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div className="fixed bottom-0 left-0 right-0 h-16 bg-surface-container-lowest/80 backdrop-blur-[12px] border-t border-outline-variant/40 z-50 flex items-center justify-between px-4 md:pl-sidebar transition-all">
      {episode ? (
        <>
          <Link
            href={`/now-playing?id=${episode.episode_id}`}
            className="flex items-center gap-4 min-w-0 flex-1"
          >
            <div className="w-10 h-10 rounded bg-surface-container-high flex-shrink-0 flex items-center justify-center">
              <Mic2 className="w-4 h-4 text-outline" strokeWidth={1.5} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="font-caption text-caption text-on-surface truncate">{episode.title}</p>
              <p className="font-label-sm text-label-sm text-on-surface-variant">
                {formatDuration(currentTime)} / {formatDuration(duration || episode.duration_seconds)}
              </p>
            </div>
          </Link>
          <div className="hidden sm:flex flex-1 max-w-xl px-8">
            <button
              onClick={(e) => {
                e.preventDefault();
                seek(0);
              }}
              className="w-full group"
            >
              <div className="w-full bg-surface-container-high rounded-full h-1 relative group-hover:h-1.5 transition-all">
                <div
                  className="bg-primary h-full rounded-full transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </button>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={togglePlay}
              className="w-10 h-10 rounded-full bg-primary flex items-center justify-center text-on-primary hover:bg-primary-container transition-colors"
            >
              {isPlaying ? (
                <Pause className="w-5 h-5" strokeWidth={1.5} />
              ) : (
                <Play className="w-5 h-5 ml-0.5" strokeWidth={1.5} />
              )}
            </button>
            <div className="relative hidden sm:block">
              {showVolume && (
                <div className="absolute bottom-full right-0 mb-2 bg-surface-container-lowest border border-outline-variant/40 rounded-lg shadow-lg p-3 flex items-center gap-2 z-50">
                  <button
                    onClick={() => setVolume(volume > 0 ? 0 : 1)}
                    className="text-outline hover:text-primary transition-colors"
                    aria-label={volume === 0 ? "Unmute" : "Mute"}
                  >
                    {volume === 0 ? (
                      <VolumeX className="w-4 h-4" strokeWidth={1.5} />
                    ) : (
                      <Volume2 className="w-4 h-4" strokeWidth={1.5} />
                    )}
                  </button>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={volume}
                    onChange={(e) => setVolume(parseFloat(e.target.value))}
                    className="w-24 accent-primary cursor-pointer"
                    aria-label="Volume"
                  />
                </div>
              )}
              <button
                onClick={() => setShowVolume((v) => !v)}
                className="flex items-center justify-center text-outline hover:text-primary transition-colors p-1"
                aria-label="Volume"
              >
                {volume === 0 ? (
                  <VolumeX className="w-5 h-5" strokeWidth={1.5} />
                ) : (
                  <Volume2 className="w-5 h-5" strokeWidth={1.5} />
                )}
              </button>
            </div>
          </div>
        </>
      ) : (
        <Link href="/discovery" className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-full bg-surface-container-high flex-shrink-0 flex items-center justify-center">
            <Play className="w-4 h-4 text-outline ml-0.5" strokeWidth={1.5} />
          </div>
          <div className="flex flex-col">
            <span className="font-caption text-caption text-on-surface">Browse episodes</span>
          </div>
        </Link>
      )}
    </div>
  );
}
