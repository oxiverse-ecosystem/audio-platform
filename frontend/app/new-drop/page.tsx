"use client";

import { useState, useRef, useCallback, useEffect } from "react";
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
} from "lucide-react";

type Stage = "idle" | "uploading" | "processing" | "ready" | "failed";

export default function NewDropPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [assetId, setAssetId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadUrls, setDownloadUrls] = useState<{ mp3: string | null; wav: string | null } | null>(null);
  const [published, setPublished] = useState(false);
  const [publishing, setPublishing] = useState(false);

  // Audio preview state
  const [isPlaying, setIsPlaying] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [user, loading, router]);

  const handleFile = useCallback((f: File | null) => {
    if (!f) return;
    setFile(f);
    setStage("idle");
    setError(null);
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
    setError(null);
  };

  const startUpload = async () => {
    if (!file) return;
    setError(null);
    setStage("uploading");
    setProgress(0);
    try {
      const res = await api.upload(file, title || file.name, "mp3", setProgress);
      setJobId(res.job_id);
      setAssetId(res.asset_id);
      setStage("processing");
    } catch (err: unknown) {
      setStage("failed");
      setError(err instanceof ApiError ? err.message : "Upload failed");
    }
  };

  const publishToDiscovery = async () => {
    if (!jobId || !assetId) return;
    setPublishing(true);
    setError(null);
    try {
      await api.createEpisode({
        asset_id: assetId,
        title: title || file?.name || "Untitled",
        description: description || undefined,
        category: "Founder Stories",
      });
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
          setDownloadUrls(status.download ? { mp3: status.download.mp3 || null, wav: status.download.wav || null } : null);
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
  }, [stage, jobId]);

  // Create local audio preview from uploaded file
  useEffect(() => {
    if (file) {
      const url = URL.createObjectURL(file);
      setAudioUrl(url);
      return () => URL.revokeObjectURL(url);
    } else {
      setAudioUrl(null);
    }
  }, [file]);

  // Audio time tracking
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTime = () => setCurrentTime(audio.currentTime);
    const onLoaded = () => setDuration(audio.duration);
    const onEnded = () => setIsPlaying(false);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("loadedmetadata", onLoaded);
    audio.addEventListener("ended", onEnded);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("loadedmetadata", onLoaded);
      audio.removeEventListener("ended", onEnded);
    };
  }, [audioUrl]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
    } else {
      audio.play();
      setIsPlaying(true);
    }
  };

  const fmt = (s: number) => {
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
        <div className="max-w-container-max mx-auto px-margin-desktop py-stack-lg">
          <header className="mb-stack-lg flex justify-between items-end">
            <div>
              <h2 className="font-headline-lg text-headline-lg text-on-surface">New Drop</h2>
              <p className="font-body-md text-body-md text-on-surface-variant mt-2">
                Upload and enhance your audio for the Oxiverse network.
              </p>
            </div>
          </header>

          {error && (
            <div className="bg-error-container text-on-error-container font-body-md text-body-md p-3 rounded-lg mb-4 flex items-center gap-2">
              <XCircle className="w-4 h-4 flex-shrink-0" />
              {error}
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
                  <p className="font-body-md text-body-md text-on-surface-variant mb-6">WAV, MP3, or FLAC up to 200MB</p>
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
                <div className="bg-surface-container-lowest border border-outline-variant rounded-xl p-6">
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-lg bg-primary-container flex items-center justify-center flex-shrink-0">
                      <FileAudio className="w-6 h-6 text-primary" strokeWidth={1.5} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-caption text-caption text-on-surface truncate">{file.name}</div>
                      <div className="font-label-sm text-label-sm text-on-surface-variant">
                        {(file.size / (1024 * 1024)).toFixed(1)} MB
                      </div>
                    </div>
                    {stage === "idle" && (
                      <button onClick={removeFile} className="text-on-surface-variant hover:text-error transition-colors">
                        <Trash2 className="w-5 h-5" strokeWidth={1.5} />
                      </button>
                    )}
                  </div>

                  {stage === "uploading" && (
                    <div className="mt-4">
                      <div className="flex justify-between font-label-sm text-label-sm text-on-surface-variant mb-1">
                        <span>Uploading</span>
                        <span>{progress}%</span>
                      </div>
                      <div className="w-full bg-surface-variant rounded-full h-2 overflow-hidden">
                        <div className="bg-primary h-2 rounded-full transition-all" style={{ width: `${progress}%` }} />
                      </div>
                    </div>
                  )}

                  {stage === "processing" && (
                    <div className="mt-4 flex items-center gap-2 text-primary">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span className="font-label-sm text-label-sm">Processing with studio enhancement…</span>
                    </div>
                  )}

                  {stage === "ready" && (
                    <div className="mt-4 space-y-3">
                      <div className="flex items-center gap-2 text-primary">
                        <CheckCircle className="w-4 h-4" />
                        <span className="font-label-sm text-label-sm">Studio enhanced and ready!</span>
                      </div>
                      {!published ? (
                        <button
                          onClick={publishToDiscovery}
                          disabled={publishing}
                          className="w-full bg-primary text-on-primary font-caption text-caption py-2.5 rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                        >
                          {publishing && <Loader2 className="w-4 h-4 animate-spin" />}
                          Publish to Discovery
                        </button>
                      ) : (
                        <div className="flex items-center gap-2 text-primary">
                          <CheckCircle className="w-4 h-4" />
                          <span className="font-label-sm text-label-sm">Published to Discovery!</span>
                        </div>
                      )}
                    </div>
                  )}

                  {stage === "failed" && (
                    <div className="mt-4 flex items-center gap-2 text-error">
                      <XCircle className="w-4 h-4" />
                      <span className="font-label-sm text-label-sm">Processing failed</span>
                    </div>
                  )}

                  {stage === "idle" && (
                    <button
                      onClick={startUpload}
                      className="mt-4 w-full bg-primary text-on-primary font-caption text-caption py-2.5 rounded-lg hover:bg-primary-container transition-colors"
                    >
                      Upload &amp; Enhance
                    </button>
                  )}
                </div>
              )}

              {/* Processing stepper */}
              <div className="bg-surface-container-lowest border border-outline-variant rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
                <h4 className="font-caption text-caption text-on-surface font-bold mb-6">Processing Pipeline</h4>
                <Step
                  step={1}
                  title="Uploaded"
                  desc={file ? `${file.name}` : "Waiting for upload"}
                  state={stage === "idle" ? "pending" : "done"}
                />
                <Step
                  step={2}
                  title="Repairing"
                  desc="Removing background noise and hum."
                  state={stage === "processing" ? "active" : stage === "ready" ? "done" : stage === "failed" ? "failed" : "pending"}
                />
                <Step
                  step={3}
                  title="Enhancing to Studio"
                  desc="Applying Oxiverse EQ and compression."
                  state={stage === "ready" ? "done" : stage === "failed" ? "failed" : "pending"}
                />
                <Step
                  step={4}
                  title="Ready"
                  desc="Your audio is enhanced."
                  state={stage === "ready" ? "done" : stage === "failed" ? "failed" : "pending"}
                />
                <Step
                  step={5}
                  title="Published"
                  desc="Listened on Discovery."
                  state={published ? "done" : "pending"}
                  last
                />
              </div>
            </div>

            {/* Right: metadata */}
            <div className="lg:col-span-5 flex flex-col gap-stack-lg">
              <div className="bg-surface-container-lowest border border-outline-variant rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] flex flex-col gap-stack-md">
                <div>
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-2">EPISODE TITLE</label>
                  <input
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3 font-caption text-caption text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all"
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Q3 Strategy & Market Adjustments"
                  />
                </div>
                <div>
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-2">DESCRIPTION</label>
                  <textarea
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3 font-caption text-caption text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all resize-none"
                    rows={4}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="A brief overview of your audio…"
                  />
                </div>
                <div className="pt-4">
                  <label className="font-label-sm text-label-sm text-on-surface-variant mb-2 block">PUBLISH</label>
                  <p className="font-caption text-caption text-on-surface-variant">Visible to everyone on Discovery.</p>
                </div>
              </div>

              {/* Audio preview */}
              <div className="bg-surface-container-low border border-outline-variant rounded-xl p-6 relative overflow-hidden">
                <div className="absolute inset-0 opacity-20 pointer-events-none" style={{ background: "linear-gradient(135deg, rgba(70,72,212,0.1) 0%, rgba(218,226,253,0.1) 100%)", backdropFilter: "blur(10px)" }} />
                <h4 className="font-caption text-caption text-on-surface font-bold mb-4 relative z-10">Enhancement Preview</h4>
                {audioUrl ? (
                  <div className="relative z-10">
                    <audio ref={audioRef} src={audioUrl} preload="metadata" />
                    <div className="flex items-center gap-4 bg-surface-container-lowest p-4 rounded-lg border border-outline-variant">
                      <button
                        onClick={togglePlay}
                        className="w-10 h-10 rounded-full bg-primary text-on-primary flex items-center justify-center hover:bg-primary-container transition-colors flex-shrink-0"
                      >
                        {isPlaying ? <Pause className="w-5 h-5" strokeWidth={1.5} /> : <Play className="w-5 h-5" strokeWidth={1.5} />}
                      </button>
                      <div className="flex-grow h-10 relative">
                        <div className="absolute inset-0 rounded bg-surface-variant" />
                        <div
                          className="absolute inset-y-0 left-0 rounded bg-primary-fixed-dim transition-all"
                          style={{ width: duration ? `${(currentTime / duration) * 100}%` : "0%" }}
                        />
                      </div>
                      <span className="font-label-sm text-label-sm text-on-surface-variant flex-shrink-0">
                        {fmt(currentTime)} / {fmt(duration)}
                      </span>
                    </div>
                    <div className="flex justify-center mt-4">
                      <div className="inline-flex bg-surface-container-lowest rounded-lg border border-outline-variant p-1">
                        <button className="px-4 py-1.5 rounded-md font-caption text-caption text-on-surface-variant hover:bg-surface-variant transition-colors">Original</button>
                        <button className="px-4 py-1.5 rounded-md font-caption text-caption bg-surface-variant text-on-surface font-bold shadow-sm">Studio Enhanced</button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-8 relative z-10">
                    <p className="font-body-md text-body-md text-on-surface-variant">Upload an audio file to preview</p>
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

function Step({ step, title, desc, state, last }: { step: number; title: string; desc: string; state: "pending" | "active" | "done" | "failed"; last?: boolean }) {
  const color =
    state === "done" ? "bg-primary" :
    state === "active" ? "bg-primary animate-pulse" :
    state === "failed" ? "bg-error" :
    "bg-surface-variant";

  const border =
    state === "done" || state === "active" || state === "failed" ? "border-primary" : "border-surface-variant";

  const opacity = state === "pending" ? "opacity-50" : "";

  return (
    <div className={`relative pl-8 ${last ? "" : "border-l-2 pb-8"} ${border} ${opacity}`}>
      <div className={`absolute -left-[9px] top-0 w-4 h-4 rounded-full ${color} ring-4 ring-surface-container-lowest flex items-center justify-center`} />
      <h5 className={`font-caption text-caption text-on-surface ${state === "active" ? "font-bold" : ""}`}>{step}. {title}</h5>
      <p className="font-label-sm text-label-sm text-on-surface-variant mt-1">{desc}</p>
      {state === "done" && <CheckCircle className="text-primary w-4 h-4 mt-2" strokeWidth={1.5} />}
      {state === "failed" && <XCircle className="text-error w-4 h-4 mt-2" strokeWidth={1.5} />}
    </div>
  );
}
