"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { useAuth } from "@/context/AuthContext";
import { api, ApiError } from "@/lib/api";
import {
  CloudUpload,
  CheckCircle,
  Play,
  Pause,
  Loader2,
  XCircle,
  FileAudio,
  Trash2,
  Sparkles,
  Mic,
  ArrowRight,
  ShieldCheck,
} from "lucide-react";

type Stage = "idle" | "uploading" | "processing" | "ready" | "failed";
type AbMode = "raw" | "enhanced";

export default function NewDropPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("Founder Stories");
  const [publishImmediate, setPublishImmediate] = useState(false);

  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [assetId, setAssetId] = useState<string | null>(null);
  const [episodeId, setEpisodeId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadUrls, setDownloadUrls] = useState<{ mp3: string | null; wav: string | null; raw: string | null } | null>(null);
  const [waveformPeaks, setWaveformPeaks] = useState<number[] | null>(null);
  const [published, setPublished] = useState(false);
  const [publishing, setPublishing] = useState(false);

  // Synchronized A/B Comparison Player State
  const [abMode, setAbMode] = useState<AbMode>("enhanced");
  const [isPlaying, setIsPlaying] = useState(false);
  const [localAudioUrl, setLocalAudioUrl] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const rawAudioRef = useRef<HTMLAudioElement | null>(null);
  const enhancedAudioRef = useRef<HTMLAudioElement | null>(null);
  const waveformContainerRef = useRef<HTMLDivElement | null>(null);

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [user, loading, router]);

  const handleFile = useCallback((f: File | null) => {
    if (!f) return;
    setFile(f);
    setStage("idle");
    setError(null);
    setDownloadUrls(null);
    setWaveformPeaks(null);
    setPublished(false);
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  }, [title]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    handleFile(f);
  }, [handleFile]);

  const removeFile = () => {
    setFile(null);
    setStage("idle");
    setProgress(0);
    setJobId(null);
    setAssetId(null);
    setEpisodeId(null);
    setError(null);
    setDownloadUrls(null);
    setWaveformPeaks(null);
    setIsPlaying(false);
  };

  // Create local audio preview from uploaded file
  useEffect(() => {
    if (file) {
      const url = URL.createObjectURL(file);
      setLocalAudioUrl(url);
      return () => URL.revokeObjectURL(url);
    } else {
      setLocalAudioUrl(null);
    }
  }, [file]);

  const startUpload = async () => {
    if (!file) return;
    setError(null);
    setStage("uploading");
    setProgress(0);
    try {
      const res = await api.upload(
        file,
        title || file.name,
        "mp3",
        {
          description: description || undefined,
          category,
          publish_immediate: publishImmediate,
        },
        setProgress
      );
      setJobId(res.job_id);
      setAssetId(res.asset_id);
      if (res.episode_id) setEpisodeId(res.episode_id);
      setStage("processing");
      if (publishImmediate) setPublished(true);
    } catch (err: unknown) {
      setStage("failed");
      setError(err instanceof ApiError ? err.message : "Upload failed");
    }
  };

  const publishToDiscovery = async () => {
    if (!episodeId && !assetId) return;
    setPublishing(true);
    setError(null);
    try {
      if (episodeId) {
        await api.publishDraft(episodeId);
      } else if (assetId) {
        await api.createEpisode({
          asset_id: assetId,
          title: title || file?.name || "Untitled",
          description: description || undefined,
          category,
        });
      }
      setPublished(true);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Failed to publish");
    } finally {
      setPublishing(false);
    }
  };

  // Poll job status while processing
  useEffect(() => {
    if (stage !== "processing" || !jobId) return;
    const interval = setInterval(async () => {
      try {
        const status = await api.getUploadStatus(jobId);
        if (status.status === "ready") {
          setStage("ready");
          const apiBase = api.API_BASE;
          setDownloadUrls({
            mp3: status.download?.mp3 ? `${apiBase}${status.download.mp3}` : null,
            wav: status.download?.wav ? `${apiBase}${status.download.wav}` : null,
            raw: status.download?.raw ? `${apiBase}${status.download.raw}` : null,
          });
          if (status.report?.waveform_peaks) {
            setWaveformPeaks(status.report.waveform_peaks);
          }
          if (publishImmediate) {
            setPublished(true);
          }
          clearInterval(interval);
        } else if (status.status === "failed") {
          setStage("failed");
          setError(status.error || "Processing failed");
          clearInterval(interval);
        }
      } catch (err: unknown) {
        setStage("failed");
        setError(err instanceof ApiError ? err.message : "Status check failed");
        clearInterval(interval);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [stage, jobId, publishImmediate]);

  // Audio elements sources
  const rawSource = downloadUrls?.raw || localAudioUrl || "";
  const enhancedSource = downloadUrls?.mp3 || "";

  // Playback & Synchronized A/B Audio Switcher (Zero Skipping)
  const togglePlay = () => {
    const rawAudio = rawAudioRef.current;
    const enhAudio = enhancedAudioRef.current;

    if (isPlaying) {
      rawAudio?.pause();
      enhAudio?.pause();
      setIsPlaying(false);
    } else {
      const activeElement = abMode === "enhanced" && enhancedSource ? enhAudio : rawAudio;
      const inactiveElement = abMode === "enhanced" && enhancedSource ? rawAudio : enhAudio;

      if (activeElement) {
        activeElement.volume = 1;
        if (inactiveElement && inactiveElement.src) {
          inactiveElement.currentTime = activeElement.currentTime;
          inactiveElement.volume = 0;
          inactiveElement.play().catch(() => {});
        }
        activeElement.play().catch(() => {});
        setIsPlaying(true);
      }
    }
  };

  const switchAbMode = (targetMode: AbMode) => {
    if (abMode === targetMode) return;
    setAbMode(targetMode);

    const rawAudio = rawAudioRef.current;
    const enhAudio = enhancedAudioRef.current;

    if (!rawAudio || !enhAudio || !enhancedSource) return;

    // Synchronize timestamps with zero-skip crossfade
    if (targetMode === "enhanced") {
      enhAudio.currentTime = rawAudio.currentTime;
      enhAudio.volume = 1;
      rawAudio.volume = 0;
    } else {
      rawAudio.currentTime = enhAudio.currentTime;
      rawAudio.volume = 1;
      enhAudio.volume = 0;
    }
  };

  // Sync timeupdates from whichever audio is primary
  useEffect(() => {
    const primaryAudio = abMode === "enhanced" && enhancedSource ? enhancedAudioRef.current : rawAudioRef.current;
    if (!primaryAudio) return;

    const onTime = () => setCurrentTime(primaryAudio.currentTime);
    const onLoaded = () => {
      if (primaryAudio.duration && !isNaN(primaryAudio.duration)) {
        setDuration(primaryAudio.duration);
      }
    };
    const onEnded = () => {
      setIsPlaying(false);
      if (rawAudioRef.current) rawAudioRef.current.currentTime = 0;
      if (enhancedAudioRef.current) enhancedAudioRef.current.currentTime = 0;
    };

    primaryAudio.addEventListener("timeupdate", onTime);
    primaryAudio.addEventListener("loadedmetadata", onLoaded);
    primaryAudio.addEventListener("ended", onEnded);

    return () => {
      primaryAudio.removeEventListener("timeupdate", onTime);
      primaryAudio.removeEventListener("loadedmetadata", onLoaded);
      primaryAudio.removeEventListener("ended", onEnded);
    };
  }, [abMode, enhancedSource, rawSource]);

  const handleSeek = (pct: number) => {
    const targetTime = pct * duration;
    setCurrentTime(targetTime);
    if (rawAudioRef.current) rawAudioRef.current.currentTime = targetTime;
    if (enhancedAudioRef.current) enhancedAudioRef.current.currentTime = targetTime;
  };

  const fmt = (s: number) => {
    if (isNaN(s) || s < 0) return "0:00";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

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
          <p className="font-body-md text-body-md text-on-surface-variant">Log in to publish audio.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-grow min-w-0 overflow-x-hidden overflow-y-auto bg-surface-bright relative md:pl-sidebar pt-14 md:pt-0 pb-24">
        <div className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop py-stack-lg">
          <header className="mb-stack-lg flex flex-col sm:flex-row sm:items-end justify-between gap-4">
            <div>
              <h2 className="font-headline-lg text-headline-lg text-on-surface">New Drop</h2>
              <p className="font-body-md text-body-md text-on-surface-variant mt-1">
                Upload raw voice notes and enhance them to broadcast studio quality with real peaks and A/B comparison.
              </p>
            </div>
            {stage === "processing" && (
              <div className="bg-primary/10 border border-primary/30 rounded-xl px-4 py-2 flex items-center gap-3">
                <Loader2 className="w-4 h-4 text-primary animate-spin flex-shrink-0" />
                <div className="font-label-sm text-label-sm text-on-surface">
                  Enhancing in background &bull;{" "}
                  <Link href="/creator" className="text-primary hover:underline font-bold">
                    Safe to leave
                  </Link>
                </div>
              </div>
            )}
          </header>

          {error && (
            <div className="bg-error-container text-on-error-container font-body-md text-body-md p-4 rounded-xl mb-6 flex items-center gap-3">
              <XCircle className="w-5 h-5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Async Leave-Page Notification Banner */}
          {(stage === "processing" || stage === "ready") && (
            <div className="bg-surface-container-lowest border border-outline-variant/60 rounded-xl p-4 mb-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 shadow-sm">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-primary-container flex items-center justify-center flex-shrink-0">
                  <ShieldCheck className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <h4 className="font-caption text-caption font-bold text-on-surface">
                    {stage === "ready" ? "Enhancement Complete & Saved in Studio" : "Saved as Draft in Studio"}
                  </h4>
                  <p className="font-label-sm text-label-sm text-on-surface-variant">
                    You can safely close this page or navigate elsewhere. Your audio draft will always be available in Creator Studio.
                  </p>
                </div>
              </div>
              <Link
                href="/creator"
                className="bg-surface-container-high hover:bg-surface-variant text-on-surface font-caption text-caption px-4 py-2 rounded-lg transition-colors flex items-center gap-2 whitespace-nowrap"
              >
                Go to Creator Studio
                <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
            {/* Left: Upload + processing */}
            <div className="lg:col-span-7 flex flex-col gap-stack-lg">
              {/* Drop zone / file info */}
              {!file ? (
                <div
                  onDrop={onDrop}
                  onDragOver={(e) => e.preventDefault()}
                  onClick={() => fileInputRef.current?.click()}
                  className="border-2 border-dashed border-outline-variant bg-surface rounded-xl p-stack-lg flex flex-col items-center justify-center text-center transition-colors hover:border-primary hover:bg-surface-container-low cursor-pointer min-h-[240px]"
                >
                  <CloudUpload className="w-10 h-10 text-on-surface-variant mb-4" strokeWidth={1.5} />
                  <h3 className="font-headline-md text-headline-md text-on-surface mb-2">Drag &amp; Drop Audio</h3>
                  <p className="font-body-md text-body-md text-on-surface-variant mb-6">WAV, MP3, FLAC, M4A up to 200MB</p>
                  <button className="bg-surface-container-lowest border border-outline-variant text-on-surface px-4 py-2 rounded-lg font-caption text-caption hover:border-primary transition-colors">
                    Browse Files
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="audio/*,.wav,.mp3,.flac,.ogg,.m4a"
                    className="hidden"
                    onChange={(e) => handleFile(e.target.files?.[0] || null)}
                  />
                </div>
              ) : (
                <div className="bg-surface-container-lowest border border-outline-variant rounded-xl p-6 shadow-sm">
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-lg bg-primary-container flex items-center justify-center flex-shrink-0">
                      <FileAudio className="w-6 h-6 text-primary" strokeWidth={1.5} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-caption text-caption text-on-surface truncate font-bold">{file.name}</div>
                      <div className="font-label-sm text-label-sm text-on-surface-variant">
                        {(file.size / (1024 * 1024)).toFixed(1)} MB
                      </div>
                    </div>
                    {stage === "idle" && (
                      <button onClick={removeFile} className="text-on-surface-variant hover:text-error transition-colors p-1">
                        <Trash2 className="w-5 h-5" strokeWidth={1.5} />
                      </button>
                    )}
                  </div>

                  {stage === "uploading" && (
                    <div className="mt-4">
                      <div className="flex justify-between font-label-sm text-label-sm text-on-surface-variant mb-1">
                        <span>Uploading to cloud storage…</span>
                        <span>{progress}%</span>
                      </div>
                      <div className="w-full bg-surface-variant rounded-full h-2 overflow-hidden">
                        <div className="bg-primary h-2 rounded-full transition-all" style={{ width: `${progress}%` }} />
                      </div>
                    </div>
                  )}

                  {stage === "processing" && (
                    <div className="mt-5 p-4 rounded-xl bg-surface-container-low border border-outline-variant/60 space-y-2">
                      <div className="flex items-center gap-2 text-primary font-bold">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span className="font-caption text-caption">Mastering with Oxiverse Studio Chain…</span>
                      </div>
                      <p className="font-label-sm text-label-sm text-on-surface-variant">
                        Applying de-clipping, de-plosive filters, adaptive noise reduction, and broadcast LUFS mastering.
                      </p>
                    </div>
                  )}

                  {stage === "ready" && (
                    <div className="mt-5 space-y-4">
                      <div className="flex items-center gap-2 text-primary font-bold">
                        <CheckCircle className="w-5 h-5" />
                        <span className="font-caption text-caption">Mastered to Studio Standard (-14 LUFS)</span>
                      </div>

                      {!published ? (
                        <button
                          onClick={publishToDiscovery}
                          disabled={publishing}
                          className="w-full bg-primary text-on-primary font-caption text-caption py-3 rounded-lg hover:bg-primary-container hover:text-on-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2 font-bold shadow-sm"
                        >
                          {publishing && <Loader2 className="w-4 h-4 animate-spin" />}
                          Publish to Discovery Network
                        </button>
                      ) : (
                        <div className="p-3 bg-primary/10 border border-primary/30 rounded-lg flex items-center gap-2 text-primary font-bold font-caption text-caption">
                          <CheckCircle className="w-4 h-4" />
                          <span>Published live on Discovery!</span>
                        </div>
                      )}
                    </div>
                  )}

                  {stage === "failed" && (
                    <div className="mt-4 flex items-center gap-2 text-error">
                      <XCircle className="w-4 h-4" />
                      <span className="font-label-sm text-label-sm">Processing failed. Please retry.</span>
                    </div>
                  )}

                  {stage === "idle" && (
                    <div className="mt-5 space-y-4">
                      <div className="flex items-center gap-3 p-3 bg-surface-container-low rounded-lg border border-outline-variant/50">
                        <input
                          id="publish_immediate"
                          type="checkbox"
                          checked={publishImmediate}
                          onChange={(e) => setPublishImmediate(e.target.checked)}
                          className="w-4 h-4 accent-primary rounded cursor-pointer"
                        />
                        <label htmlFor="publish_immediate" className="font-caption text-caption text-on-surface cursor-pointer select-none">
                          <span className="font-bold">Publish ahead:</span> Auto-publish to Discovery as soon as processing finishes
                        </label>
                      </div>

                      <button
                        onClick={startUpload}
                        className="w-full bg-primary text-on-primary font-caption text-caption py-3 rounded-lg hover:bg-on-primary-fixed-variant transition-colors font-bold shadow-sm"
                      >
                        {publishImmediate ? "Upload & Auto-Publish" : "Upload & Save to Drafts"}
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Processing stepper */}
              <div className="bg-surface-container-lowest border border-outline-variant rounded-xl p-6 shadow-sm">
                <h4 className="font-caption text-caption text-on-surface font-bold mb-6">Mastering Pipeline</h4>
                <Step
                  step={1}
                  title="Uploaded"
                  desc={file ? `${file.name}` : "Waiting for voice file"}
                  state={stage === "idle" ? "pending" : "done"}
                />
                <Step
                  step={2}
                  title="Mobile Repair"
                  desc="Declipping, deplosive filtering, and dead-air lead trim."
                  state={stage === "processing" ? "active" : stage === "ready" ? "done" : stage === "failed" ? "failed" : "pending"}
                />
                <Step
                  step={3}
                  title="Studio Enhancement & Peak Extraction"
                  desc="Broadcast EQ, dynamic loudness targeting, and waveform peak generation."
                  state={stage === "processing" ? "active" : stage === "ready" ? "done" : stage === "failed" ? "failed" : "pending"}
                />
                <Step
                  step={4}
                  title="Studio Ready & A/B Comparison"
                  desc="Dual-track raw and mastered audio available for live preview."
                  state={stage === "ready" ? "done" : stage === "failed" ? "failed" : "pending"}
                />
                <Step
                  step={5}
                  title="Published"
                  desc="Distributed on Discovery with listener watermarking."
                  state={published ? "done" : "pending"}
                  last
                />
              </div>
            </div>

            {/* Right: metadata & Synchronized A/B Audio Comparison Player */}
            <div className="lg:col-span-5 flex flex-col gap-stack-lg">
              <div className="bg-surface-container-lowest border border-outline-variant rounded-xl p-6 shadow-sm flex flex-col gap-stack-md">
                <div>
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-2">EPISODE TITLE</label>
                  <input
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3 font-caption text-caption text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all"
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="E.g., Q3 Strategy & Pitch Breakdown"
                  />
                </div>
                <div>
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-2">CATEGORY</label>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3 font-caption text-caption text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all"
                  >
                    <option value="Founder Stories">Founder Stories</option>
                    <option value="Tech">Tech</option>
                    <option value="Business">Business</option>
                    <option value="Product">Product</option>
                    <option value="Design">Design</option>
                  </select>
                </div>
                <div>
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-2">DESCRIPTION</label>
                  <textarea
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3 font-caption text-caption text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all resize-none"
                    rows={3}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Brief background or show notes…"
                  />
                </div>
              </div>

              {/* Synchronized A/B Audio Comparison Player */}
              <div className="bg-surface-container-lowest border border-outline-variant rounded-xl p-6 relative overflow-hidden shadow-sm">
                <div className="flex items-center justify-between mb-4">
                  <h4 className="font-caption text-caption text-on-surface font-bold flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-primary" />
                    Synchronized A/B Player
                  </h4>
                  {enhancedSource ? (
                    <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                      Zero-Skip Sync Active
                    </span>
                  ) : (
                    <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-surface-variant text-on-surface-variant">
                      Raw Preview
                    </span>
                  )}
                </div>

                {rawSource ? (
                  <div className="space-y-4">
                    {/* Hidden synchronized audio elements */}
                    <audio ref={rawAudioRef} src={rawSource} preload="auto" />
                    {enhancedSource && (
                      <audio ref={enhancedAudioRef} src={enhancedSource} preload="auto" />
                    )}

                    {/* Mode badge indicator */}
                    <div className="p-3 rounded-lg border border-outline-variant/60 bg-surface-container-low flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {abMode === "enhanced" ? (
                          <>
                            <Sparkles className="w-4 h-4 text-primary flex-shrink-0" />
                            <div>
                              <div className="font-caption text-caption font-bold text-primary">Studio Enhanced Track</div>
                              <div className="font-label-sm text-[11px] text-on-surface-variant">
                                48kHz Broadcast chain &bull; -14 LUFS &bull; De-clipped
                              </div>
                            </div>
                          </>
                        ) : (
                          <>
                            <Mic className="w-4 h-4 text-outline flex-shrink-0" />
                            <div>
                              <div className="font-caption text-caption font-bold text-on-surface">Original Raw Recording</div>
                              <div className="font-label-sm text-[11px] text-on-surface-variant">
                                Unprocessed phone mic capture
                              </div>
                            </div>
                          </>
                        )}
                      </div>
                    </div>

                    {/* True Waveform Visualizer */}
                    <div
                      ref={waveformContainerRef}
                      onClick={(e) => {
                        const rect = e.currentTarget.getBoundingClientRect();
                        const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                        handleSeek(pct);
                      }}
                      className="h-16 bg-surface-container-low border border-outline-variant/50 rounded-lg p-2 flex items-center justify-between gap-[2px] cursor-pointer hover:border-primary transition-colors overflow-hidden"
                      title="Click to seek"
                    >
                      {waveformPeaks && waveformPeaks.length > 0 ? (
                        waveformPeaks.slice(0, 48).map((peak, idx) => {
                          const activeProgress = duration > 0 ? currentTime / duration : 0;
                          const isBarActive = idx / 48 <= activeProgress;
                          const heightPct = Math.max(12, Math.round(peak * 100));
                          return (
                            <div
                              key={idx}
                              className={`flex-1 rounded-full transition-all duration-75 ${
                                isBarActive
                                  ? abMode === "enhanced"
                                    ? "bg-primary"
                                    : "bg-secondary-fixed-dim"
                                  : "bg-outline-variant/50"
                              }`}
                              style={{ height: `${heightPct}%` }}
                            />
                          );
                        })
                      ) : (
                        // Fallback waveform during initial file selection before mastering
                        Array.from({ length: 48 }).map((_, idx) => {
                          const activeProgress = duration > 0 ? currentTime / duration : 0;
                          const isBarActive = idx / 48 <= activeProgress;
                          // Deterministic pseudo-waveform for visual aesthetics
                          const heightPct = 15 + Math.round(Math.abs(Math.sin((idx * 0.3) + 1)) * 70);
                          return (
                            <div
                              key={idx}
                              className={`flex-1 rounded-full transition-all duration-75 ${
                                isBarActive ? "bg-primary" : "bg-outline-variant/40"
                              }`}
                              style={{ height: `${heightPct}%` }}
                            />
                          );
                        })
                      )}
                    </div>

                    {/* Transport controls */}
                    <div className="flex items-center gap-4 bg-surface-container-low p-3 rounded-lg border border-outline-variant/60">
                      <button
                        onClick={togglePlay}
                        className="w-10 h-10 rounded-full bg-primary text-on-primary flex items-center justify-center hover:bg-primary-container hover:text-on-primary-container transition-colors flex-shrink-0"
                      >
                        {isPlaying ? <Pause className="w-5 h-5" strokeWidth={1.5} /> : <Play className="w-5 h-5 ml-0.5" strokeWidth={1.5} />}
                      </button>
                      <div className="flex-grow">
                        <div className="flex justify-between font-label-sm text-label-sm text-on-surface-variant">
                          <span>{fmt(currentTime)}</span>
                          <span>{fmt(duration)}</span>
                        </div>
                      </div>
                    </div>

                    {/* Seamless A/B Toggle Buttons */}
                    <div className="flex justify-center pt-1">
                      <div className="inline-flex bg-surface-container-low rounded-lg border border-outline-variant/60 p-1 gap-1">
                        <button
                          onClick={() => switchAbMode("raw")}
                          disabled={!enhancedSource}
                          className={`px-4 py-2 rounded-md font-caption text-caption transition-all flex items-center gap-1.5 ${
                            abMode === "raw"
                              ? "bg-surface text-on-surface font-bold shadow-sm"
                              : "text-on-surface-variant hover:text-on-surface disabled:opacity-40"
                          }`}
                        >
                          <Mic className="w-3.5 h-3.5" />
                          Original
                        </button>
                        <button
                          onClick={() => switchAbMode("enhanced")}
                          disabled={!enhancedSource}
                          className={`px-4 py-2 rounded-md font-caption text-caption transition-all flex items-center gap-1.5 ${
                            abMode === "enhanced"
                              ? "bg-primary text-on-primary font-bold shadow-sm"
                              : "text-on-surface-variant hover:text-on-surface disabled:opacity-40"
                          }`}
                        >
                          <Sparkles className="w-3.5 h-3.5" />
                          Studio Enhanced
                        </button>
                      </div>
                    </div>
                    {!enhancedSource && stage !== "processing" && (
                      <p className="text-center font-label-sm text-[11px] text-on-surface-variant">
                        Upload to unlock instant zero-skip A/B comparison
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="text-center py-10">
                    <p className="font-body-md text-body-md text-on-surface-variant">Upload an audio file to preview and compare</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function Step({
  step,
  title,
  desc,
  state,
  last,
}: {
  step: number;
  title: string;
  desc: string;
  state: "pending" | "active" | "done" | "failed";
  last?: boolean;
}) {
  const color =
    state === "done"
      ? "bg-primary text-on-primary"
      : state === "active"
      ? "bg-primary animate-pulse text-on-primary"
      : state === "failed"
      ? "bg-error text-on-error"
      : "bg-surface-variant text-on-surface-variant";

  const border =
    state === "done" || state === "active" || state === "failed"
      ? "border-primary"
      : "border-surface-variant";

  const opacity = state === "pending" ? "opacity-60" : "";

  return (
    <div className={`relative pl-8 ${last ? "" : "border-l-2 pb-7"} ${border} ${opacity}`}>
      <div className={`absolute -left-[9px] top-0 w-4 h-4 rounded-full ${color} ring-4 ring-surface-container-lowest flex items-center justify-center`} />
      <h5 className={`font-caption text-caption text-on-surface ${state === "active" ? "font-bold" : ""}`}>
        {step}. {title}
      </h5>
      <p className="font-label-sm text-label-sm text-on-surface-variant mt-0.5">{desc}</p>
    </div>
  );
}
