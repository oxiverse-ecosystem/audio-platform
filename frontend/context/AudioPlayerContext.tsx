"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import Hls from "hls.js";
import { api, EpisodeResponse } from "@/lib/api";

interface AudioPlayerState {
  episode: EpisodeResponse | null;
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  volume: number;
  playbackRate: number;
  loading: boolean;
}

interface AudioPlayerActions {
  play: (episode: EpisodeResponse) => Promise<void>;
  togglePlay: () => void;
  seek: (time: number) => void;
  setVolume: (vol: number) => void;
  setPlaybackRate: (rate: number) => void;
}

const AudioPlayerContext = createContext<AudioPlayerState & AudioPlayerActions>(
  {
    episode: null,
    isPlaying: false,
    currentTime: 0,
    duration: 0,
    volume: 1,
    playbackRate: 1,
    loading: false,
    play: async () => {},
    togglePlay: () => {},
    seek: () => {},
    setVolume: () => {},
    setPlaybackRate: () => {},
  }
);

export function useAudioPlayer() {
  return useContext(AudioPlayerContext);
}

export function AudioPlayerProvider({ children }: { children: React.ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [episode, setEpisode] = useState<EpisodeResponse | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolumeState] = useState(1);
  const [playbackRate, setPlaybackRateState] = useState(1);
  const [loading, setLoading] = useState(false);

  // Create hidden audio element on mount
  useEffect(() => {
    const audio = new Audio();
    audio.preload = "auto";
    audioRef.current = audio;

    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    const onDurationChange = () => setDuration(audio.duration || 0);
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onEnded = () => setIsPlaying(false);
    const onVolumeChange = () => setVolumeState(audio.volume);

    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("durationchange", onDurationChange);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("volumechange", onVolumeChange);

    return () => {
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("durationchange", onDurationChange);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("volumechange", onVolumeChange);
      hlsRef.current?.destroy();
      audio.pause();
      audio.src = "";
    };
  }, []);

  const play = useCallback(async (ep: EpisodeResponse) => {
    const audio = audioRef.current;
    if (!audio) return;

    // Destroy previous HLS instance
    hlsRef.current?.destroy();
    hlsRef.current = null;
    audio.pause();

    setLoading(true);
    setEpisode(ep);
    setCurrentTime(0);
    setDuration(0);

    try {
      const session = await api.createStreamSession(ep.asset_id);
      const m3u8 = await api.getStreamPlaylist(session.session_id);
      const blob = new Blob([m3u8], { type: "application/vnd.apple.mpegurl" });
      const url = URL.createObjectURL(blob);

      if (Hls.isSupported()) {
        const hls = new Hls({
          enableWorker: true,
          lowLatencyMode: false,
          // Start playing as soon as the first bytes arrive; keep only a small
          // target buffer so short episodes don't "buffer/stall" at the tail.
          startLevel: 0,
          maxBufferLength: 6,
          maxMaxBufferLength: 12,
          backBufferLength: 0,
          fragLoadingTimeOut: 15000,
          fragLoadingMaxRetry: 6,
          fragLoadingRetryDelay: 250,
          manifestLoadingMaxRetry: 4,
        });
        hlsRef.current = hls;
        hls.loadSource(url);
        hls.attachMedia(audio);
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          audio.play().catch(() => {});
        });
        hls.on(Hls.Events.ERROR, (_event, data) => {
          if (data.fatal) {
            console.error("HLS fatal error", data);
          }
        });
      } else if (audio.canPlayType("application/vnd.apple.mpegurl")) {
        audio.src = url;
        audio.play().catch(() => {});
      }
    } catch (err) {
      console.error("Failed to start playback", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) audio.play().catch(() => {});
    else audio.pause();
  }, []);

  const seek = useCallback((time: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = time;
  }, []);

  const setVolume = useCallback((vol: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.volume = Math.max(0, Math.min(1, vol));
  }, []);

  const setPlaybackRate = useCallback((rate: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.playbackRate = rate;
    setPlaybackRateState(rate);
  }, []);

  return (
    <AudioPlayerContext.Provider
      value={{
        episode,
        isPlaying,
        currentTime,
        duration,
        volume,
        playbackRate,
        loading,
        play,
        togglePlay,
        seek,
        setVolume,
        setPlaybackRate,
      }}
    >
      {children}
    </AudioPlayerContext.Provider>
  );
}
