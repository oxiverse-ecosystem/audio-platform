"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { useAuth } from "@/context/AuthContext";
import { api, ApiError, EpisodeResponse, TimeseriesResponse, TimeseriesPoint } from "@/lib/api";
import {
  Headphones,
  User,
  Clock,
  TrendingUp,
  Landmark,
  Loader2,
  FileAudio,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Play,
  ArrowUpRight,
  Plus,
  Edit3,
  Trash2,
  X,
  RotateCw,
} from "lucide-react";

interface Analytics {
  total_episodes: number;
  total_plays: number;
  total_duration_seconds: number;
  total_earnings: number;
}

const CATEGORIES = [
  "Founder Stories",
  "Tech & AI",
  "Venture Capital",
  "Product & Design",
  "Growth & Marketing",
  "Crypto & Web3",
  "Personal Development",
];

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
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Time-series state
  const [timeframe, setTimeframe] = useState<number>(30);
  const [timeseries, setTimeseries] = useState<TimeseriesResponse | null>(null);
  const [loadingTimeseries, setLoadingTimeseries] = useState(false);
  const [hoveredPoint, setHoveredPoint] = useState<TimeseriesPoint | null>(null);

  // Drafts and creator episodes state
  const [drafts, setDrafts] = useState<EpisodeResponse[]>([]);
  const [myEpisodes, setMyEpisodes] = useState<EpisodeResponse[]>([]);
  const [publishingDraftId, setPublishingDraftId] = useState<string | null>(null);

  // Edit / Delete Modal State
  const [editingEpisode, setEditingEpisode] = useState<EpisodeResponse | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editCategory, setEditCategory] = useState("Founder Stories");
  const [editDescription, setEditDescription] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [user, loading, router]);

  // Load summary stats
  useEffect(() => {
    if (!user) return;
    api.getMyAnalytics()
      .then(setStats)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load analytics"));
  }, [user]);

  // Load time-series analytics
  useEffect(() => {
    if (!user) return;
    setLoadingTimeseries(true);
    api.getCreatorTimeseries(timeframe)
      .then(setTimeseries)
      .catch(() => setTimeseries(null))
      .finally(() => setLoadingTimeseries(false));
  }, [user, timeframe]);

  // Load drafts and creator's episodes (published)
  const refreshEpisodesAndDrafts = () => {
    if (!user) return;
    setIsRefreshing(true);
    Promise.allSettled([
      api.getDrafts().then((d) => setDrafts(d.drafts || [])),
      api.getMyEpisodes("published").then((d) => setMyEpisodes(d.episodes || [])),
    ]).finally(() => setIsRefreshing(false));
  };

  useEffect(() => {
    refreshEpisodesAndDrafts();
  }, [user]);

  const handlePublishDraft = async (draftId: string) => {
    setPublishingDraftId(draftId);
    setError(null);
    try {
      await api.publishDraft(draftId);
      setSuccessMessage("Episode published successfully to discovery!");
      setTimeout(() => setSuccessMessage(null), 3500);
      refreshEpisodesAndDrafts();
      if (stats) {
        api.getMyAnalytics().then(setStats).catch(() => {});
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to publish draft");
    } finally {
      setPublishingDraftId(null);
    }
  };

  const startEditing = (ep: EpisodeResponse) => {
    setEditingEpisode(ep);
    setEditTitle(ep.title);
    setEditCategory(ep.category || "Founder Stories");
    setEditDescription(ep.description || "");
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingEpisode) return;
    if (!editTitle.trim()) {
      setError("Title cannot be empty");
      return;
    }
    setSavingEdit(true);
    setError(null);
    try {
      await api.updateEpisode(editingEpisode.episode_id, {
        title: editTitle.trim(),
        category: editCategory,
        description: editDescription.trim() || undefined,
      });
      setEditingEpisode(null);
      setSuccessMessage("Changes saved successfully.");
      setTimeout(() => setSuccessMessage(null), 3000);
      refreshEpisodesAndDrafts();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Failed to update episode");
    } finally {
      setSavingEdit(false);
    }
  };

  const handleDeleteEpisode = async (episodeId: string) => {
    setDeletingId(episodeId);
    setError(null);
    try {
      await api.deleteEpisode(episodeId);
      setConfirmDeleteId(null);
      setSuccessMessage("Draft deleted.");
      setTimeout(() => setSuccessMessage(null), 3000);
      refreshEpisodesAndDrafts();
      if (stats) {
        api.getMyAnalytics().then(setStats).catch(() => {});
      }
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : "Failed to delete episode");
    } finally {
      setDeletingId(null);
    }
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
          <p className="font-body-md text-body-md text-on-surface-variant">Log in to view your creator studio.</p>
        </div>
      </div>
    );
  }

  const MONTHLY_QUOTA_SECONDS = 21600;

  const STATS = stats
    ? [
        { label: "Total Episodes", value: formatNumber(stats.total_episodes), delta: "Published", icon: Headphones, up: true },
        { label: "Total Plays", value: formatNumber(stats.total_plays), delta: "All time", icon: User, up: true },
        { label: "Retention Rate", value: timeseries ? `${timeseries.overall_retention_rate}%` : "100%", delta: "Completion", icon: TrendingUp, up: true },
        { label: "Quota Left", value: formatHours(Math.max(0, MONTHLY_QUOTA_SECONDS - stats.total_duration_seconds)), delta: "Free tier this month", icon: Landmark, up: true },
      ]
    : [];

  // SVG Chart Geometry
  const points = timeseries?.points || [];
  const maxPlays = Math.max(5, ...points.map((p) => p.plays));
  const chartHeight = 180;
  const chartWidth = 700;
  const paddingX = 20;
  const paddingY = 20;
  const innerW = chartWidth - paddingX * 2;
  const innerH = chartHeight - paddingY * 2;

  const polylineCoords = points.map((p, idx) => {
    const x = paddingX + (points.length > 1 ? (idx / (points.length - 1)) * innerW : innerW / 2);
    const y = paddingY + innerH - (p.plays / maxPlays) * innerH;
    return { x, y, point: p };
  });

  const pathD = polylineCoords.length > 0
    ? `M ${polylineCoords[0].x} ${polylineCoords[0].y} ` +
      polylineCoords.slice(1).map((c) => `L ${c.x} ${c.y}`).join(" ")
    : "";

  const areaD = polylineCoords.length > 0
    ? `${pathD} L ${polylineCoords[polylineCoords.length - 1].x} ${chartHeight - paddingY} L ${polylineCoords[0].x} ${chartHeight - paddingY} Z`
    : "";

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 min-w-0 overflow-x-hidden overflow-y-auto md:pl-sidebar pt-14 md:pt-0 pb-24">
        <div className="max-w-container-max mx-auto p-margin-mobile md:p-margin-desktop space-y-stack-lg">
          <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 pb-stack-md border-b border-outline-variant/50">
            <div>
              <h2 className="font-headline-lg-mobile md:font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface mb-1">
                Creator Studio
              </h2>
              <p className="font-body-md text-body-md text-on-surface-variant">
                Time-series listening analytics, voice drop drafts, and studio mastering.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={refreshEpisodesAndDrafts}
                disabled={isRefreshing}
                className="p-2.5 rounded-lg border border-outline-variant/60 text-on-surface hover:bg-surface-container-high transition-colors disabled:opacity-50"
                title="Refresh studio data"
              >
                <RotateCw className={`w-4 h-4 ${isRefreshing ? "animate-spin text-primary" : ""}`} />
              </button>
              <Link
                href="/new-drop"
                className="bg-primary text-on-primary font-caption text-caption px-4 py-2.5 rounded-lg font-bold hover:bg-on-primary-fixed-variant transition-colors flex items-center gap-2 shadow-sm"
              >
                <Plus className="w-4 h-4" />
                New Voice Drop
              </Link>
            </div>
          </header>

          {successMessage && (
            <div className="bg-primary-container text-on-primary-container font-body-md text-body-md p-3 rounded-lg flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-primary" />
              <span>{successMessage}</span>
            </div>
          )}

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

          {/* Time-Series Creator Analytics Chart */}
          <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
              <div>
                <h3 className="font-headline-md text-headline-md text-on-surface flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-primary" />
                  Listens &amp; Retention Over Time
                </h3>
                <p className="font-label-sm text-label-sm text-on-surface-variant mt-0.5">
                  Daily play volume and completed listener sessions
                </p>
              </div>

              {/* Timeframe Selector */}
              <div className="flex bg-surface-container-low p-1 rounded-lg border border-outline-variant/50 self-start">
                <button
                  onClick={() => setTimeframe(7)}
                  className={`px-3 py-1 rounded text-sm font-caption transition-all ${
                    timeframe === 7 ? "bg-primary text-on-primary font-bold shadow-sm" : "text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  7 Days
                </button>
                <button
                  onClick={() => setTimeframe(30)}
                  className={`px-3 py-1 rounded text-sm font-caption transition-all ${
                    timeframe === 30 ? "bg-primary text-on-primary font-bold shadow-sm" : "text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  30 Days
                </button>
                <button
                  onClick={() => setTimeframe(90)}
                  className={`px-3 py-1 rounded text-sm font-caption transition-all ${
                    timeframe === 90 ? "bg-primary text-on-primary font-bold shadow-sm" : "text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  90 Days
                </button>
              </div>
            </div>

            {loadingTimeseries ? (
              <div className="h-56 flex items-center justify-center text-on-surface-variant">
                <Loader2 className="w-6 h-6 animate-spin text-primary mr-2" />
                <span className="font-caption text-caption">Loading time-series analytics…</span>
              </div>
            ) : points.length > 0 ? (
              <div>
                {/* SVG Area Chart */}
                <div className="w-full overflow-x-auto">
                  <svg
                    viewBox={`0 0 ${chartWidth} ${chartHeight}`}
                    className="w-full h-56 overflow-visible select-none"
                  >
                    <defs>
                      <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#4648d4" stopOpacity="0.35" />
                        <stop offset="100%" stopColor="#4648d4" stopOpacity="0.0" />
                      </linearGradient>
                    </defs>

                    {/* Horizontal Grid lines */}
                    {[0, 0.5, 1].map((frac, idx) => {
                      const y = paddingY + innerH * (1 - frac);
                      const val = Math.round(maxPlays * frac);
                      return (
                        <g key={idx}>
                          <line
                            x1={paddingX}
                            y1={y}
                            x2={chartWidth - paddingX}
                            y2={y}
                            stroke="currentColor"
                            className="text-outline-variant/30"
                            strokeDasharray="4 4"
                          />
                          <text
                            x={paddingX}
                            y={y - 4}
                            fill="currentColor"
                            className="text-[10px] text-on-surface-variant/60 font-mono"
                          >
                            {val}
                          </text>
                        </g>
                      );
                    })}

                    {/* Area fill */}
                    {areaD && <path d={areaD} fill="url(#areaGradient)" />}

                    {/* Line stroke */}
                    {pathD && (
                      <path
                        d={pathD}
                        fill="none"
                        stroke="#4648d4"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    )}

                    {/* Interactive dots */}
                    {polylineCoords.map((coord, idx) => (
                      <g
                        key={idx}
                        className="cursor-pointer"
                        onMouseEnter={() => setHoveredPoint(coord.point)}
                        onMouseLeave={() => setHoveredPoint(null)}
                      >
                        <circle
                          cx={coord.x}
                          cy={coord.y}
                          r={hoveredPoint?.date === coord.point.date ? 5.5 : 3.5}
                          className={`transition-all duration-150 ${
                            hoveredPoint?.date === coord.point.date
                              ? "fill-primary stroke-white stroke-2"
                              : "fill-primary"
                          }`}
                        />
                      </g>
                    ))}
                  </svg>
                </div>

                {/* Hover Details Card */}
                <div className="mt-3 min-h-[32px] flex items-center justify-between text-xs text-on-surface-variant border-t border-outline-variant/40 pt-3">
                  {hoveredPoint ? (
                    <div className="flex items-center gap-4">
                      <span className="font-bold text-on-surface font-mono">{hoveredPoint.date}</span>
                      <span>
                        Plays: <strong className="text-primary">{hoveredPoint.plays}</strong>
                      </span>
                      <span>
                        Retention:{" "}
                        <strong className="text-on-surface">{hoveredPoint.completion_rate}%</strong> completed
                      </span>
                      <span>
                        Avg Listen:{" "}
                        <strong className="text-on-surface">{Math.round(hoveredPoint.avg_duration_seconds)}s</strong>
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between w-full">
                      <span>Hover over points to inspect daily listen retention</span>
                      <div className="flex items-center gap-4">
                        <span>
                          Total Period Plays: <strong className="text-primary">{timeseries?.total_plays}</strong>
                        </span>
                        <span>
                          Overall Retention:{" "}
                          <strong className="text-on-surface">{timeseries?.overall_retention_rate}%</strong>
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="h-48 flex items-center justify-center text-on-surface-variant font-body-md">
                No listening data yet for this period. Upload episodes and start listening!
              </div>
            )}
          </div>

          {/* Drafts & In-Progress Uploads Section */}
          <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="font-headline-md text-headline-md text-on-surface flex items-center gap-2">
                  <FileAudio className="w-5 h-5 text-primary" />
                  Drafts &amp; In-Progress Voice Drops
                </h3>
                <p className="font-label-sm text-label-sm text-on-surface-variant mt-0.5">
                  Audio processing in the cloud or waiting for your publish confirmation.
                </p>
              </div>
              <span className="text-xs bg-surface-container-high text-on-surface-variant font-bold px-2.5 py-1 rounded-full">
                {drafts.length} {drafts.length === 1 ? "draft" : "drafts"}
              </span>
            </div>

            {drafts.length === 0 ? (
              <div className="py-8 text-center border border-dashed border-outline-variant/60 rounded-xl bg-surface-container-low/30">
                <FileAudio className="w-8 h-8 text-on-surface-variant mx-auto mb-2 opacity-50" strokeWidth={1.5} />
                <p className="font-caption text-caption text-on-surface-variant">No pending drafts.</p>
                <p className="font-label-sm text-label-sm text-on-surface-variant/70 mt-1">
                  Upload audio in New Drop — you can leave anytime and it will stay safely in Drafts.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {drafts.map((d) => {
                  const isProcessing = d.status === "processing";
                  const isReady = d.status === "ready";
                  return (
                    <div
                      key={d.episode_id}
                      className="p-4 rounded-xl bg-surface-container-low border border-outline-variant/60 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:border-primary-fixed-dim transition-colors"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-10 h-10 rounded-lg bg-surface-container-high flex items-center justify-center flex-shrink-0">
                          <FileAudio className="w-5 h-5 text-primary" />
                        </div>
                        <div className="min-w-0">
                          <h4 className="font-caption text-caption font-bold text-on-surface truncate">
                            {d.title}
                          </h4>
                          <div className="flex items-center gap-2 text-xs text-on-surface-variant mt-0.5">
                            <span>{d.category}</span>
                            <span>&bull;</span>
                            <span>{d.duration_seconds > 0 ? `${Math.round(d.duration_seconds)}s` : "Processing…"}</span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {isProcessing && (
                          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 text-primary border border-primary/20 text-xs font-bold">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            <span>Enhancing in cloud…</span>
                          </div>
                        )}

                        {isReady && (
                          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-secondary-fixed text-on-secondary-fixed text-xs font-bold">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span>Ready to publish</span>
                          </div>
                        )}

                        <button
                          onClick={() => startEditing(d)}
                          className="p-2 text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high rounded-lg transition-colors"
                          title="Edit draft details"
                        >
                          <Edit3 className="w-4 h-4" />
                        </button>

                        {confirmDeleteId === d.episode_id ? (
                          <div className="flex items-center gap-1 bg-surface-container-high p-1 rounded-lg">
                            <button
                              onClick={() => handleDeleteEpisode(d.episode_id)}
                              disabled={deletingId === d.episode_id}
                              className="px-2.5 py-1 bg-error text-on-error text-xs font-bold rounded hover:opacity-90 transition-opacity"
                            >
                              {deletingId === d.episode_id ? "Deleting…" : "Confirm"}
                            </button>
                            <button
                              onClick={() => setConfirmDeleteId(null)}
                              className="px-2 py-1 text-xs text-on-surface-variant hover:text-on-surface"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setConfirmDeleteId(d.episode_id)}
                            className="p-2 text-on-surface-variant hover:text-error hover:bg-error-container/40 rounded-lg transition-colors"
                            title="Delete draft"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}

                        <button
                          onClick={() => handlePublishDraft(d.episode_id)}
                          disabled={publishingDraftId === d.episode_id}
                          className="px-4 py-2 bg-primary text-on-primary font-caption text-caption font-bold rounded-lg hover:bg-on-primary-fixed-variant transition-colors disabled:opacity-50 flex items-center gap-1.5 whitespace-nowrap"
                        >
                          {publishingDraftId === d.episode_id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <ArrowUpRight className="w-4 h-4" />
                          )}
                          Publish Now
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Published Episodes Section */}
          <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="font-headline-md text-headline-md text-on-surface flex items-center gap-2">
                  <Headphones className="w-5 h-5 text-primary" />
                  Your Published Episodes
                </h3>
                <p className="font-label-sm text-label-sm text-on-surface-variant mt-0.5">
                  Live on the Oxiverse Discovery network
                </p>
              </div>
              <span className="text-xs bg-surface-container-high text-on-surface-variant font-bold px-2.5 py-1 rounded-full">
                {myEpisodes.length} {myEpisodes.length === 1 ? "episode" : "episodes"}
              </span>
            </div>

            {myEpisodes.length === 0 ? (
              <div className="py-8 text-center border border-dashed border-outline-variant/60 rounded-xl bg-surface-container-low/30">
                <p className="font-caption text-caption text-on-surface-variant">No published episodes yet.</p>
                <Link href="/new-drop" className="text-primary font-bold hover:underline text-xs mt-1 inline-block">
                  Upload your first drop &rarr;
                </Link>
              </div>
            ) : (
              <div className="space-y-3">
                {myEpisodes.map((ep) => (
                  <div
                    key={ep.episode_id}
                    className="p-4 rounded-xl bg-surface-container-low border border-outline-variant/60 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:border-primary transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-10 h-10 rounded-lg bg-primary-container flex items-center justify-center flex-shrink-0">
                        <Play className="w-5 h-5 text-primary ml-0.5" />
                      </div>
                      <div className="min-w-0">
                        <h4 className="font-caption text-caption font-bold text-on-surface truncate">
                          {ep.title}
                        </h4>
                        <div className="flex items-center gap-2 text-xs text-on-surface-variant mt-0.5">
                          <span>{ep.category}</span>
                          <span>&bull;</span>
                          <span>{Math.round(ep.duration_seconds)}s</span>
                          <span>&bull;</span>
                          <span className="text-primary font-bold">{ep.play_count} plays</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 self-start sm:self-auto">
                      <button
                        onClick={() => startEditing(ep)}
                        className="p-2 text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high rounded-lg transition-colors"
                        title="Edit episode details"
                      >
                        <Edit3 className="w-4 h-4" />
                      </button>

                      <Link
                        href={`/now-playing?id=${ep.episode_id}`}
                        className="px-4 py-2 bg-surface-container-high hover:bg-surface-variant text-on-surface font-caption text-caption font-bold rounded-lg transition-colors flex items-center gap-1.5"
                      >
                        Listen
                        <ArrowUpRight className="w-4 h-4" />
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Edit Episode / Draft Modal */}
      {editingEpisode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-surface-container-lowest border border-outline-variant/60 rounded-2xl p-6 sm:p-8 max-w-lg w-full shadow-2xl space-y-6">
            <div className="flex items-center justify-between pb-4 border-b border-outline-variant/40">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-primary/10 text-primary">
                  <Edit3 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-headline-md text-headline-md text-on-surface">
                    {editingEpisode.status === "published" ? "Edit Episode Details" : "Edit Draft"}
                  </h3>
                  <p className="font-label-sm text-label-sm text-on-surface-variant">
                    {editingEpisode.status === "published"
                      ? "Update the title, category, or notes for discovery"
                      : "Refine your voice drop before publishing"}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setEditingEpisode(null)}
                className="p-1.5 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveEdit} className="space-y-4">
              <div>
                <label className="block font-label-sm text-label-sm text-on-surface-variant mb-1 font-bold">
                  Title
                </label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  required
                  className="w-full px-3.5 py-2.5 rounded-lg bg-surface-container-low border border-outline-variant text-on-surface focus:outline-none focus:border-primary text-sm font-medium"
                  placeholder="Episode title..."
                />
              </div>

              <div>
                <label className="block font-label-sm text-label-sm text-on-surface-variant mb-1 font-bold">
                  Category
                </label>
                <select
                  value={editCategory}
                  onChange={(e) => setEditCategory(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-lg bg-surface-container-low border border-outline-variant text-on-surface focus:outline-none focus:border-primary text-sm"
                >
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block font-label-sm text-label-sm text-on-surface-variant mb-1 font-bold">
                  Episode Notes / Description
                </label>
                <textarea
                  rows={4}
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-lg bg-surface-container-low border border-outline-variant text-on-surface focus:outline-none focus:border-primary text-sm resize-none"
                  placeholder="Provide context or key takeaways for your listeners..."
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-4 border-t border-outline-variant/40">
                <button
                  type="button"
                  onClick={() => setEditingEpisode(null)}
                  disabled={savingEdit}
                  className="px-4 py-2.5 rounded-lg border border-outline-variant text-on-surface-variant hover:bg-surface-container font-caption text-caption font-bold transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingEdit || !editTitle.trim()}
                  className="px-5 py-2.5 bg-primary text-on-primary rounded-lg font-caption text-caption font-bold hover:bg-on-primary-fixed-variant transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                  {savingEdit && <Loader2 className="w-4 h-4 animate-spin" />}
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
