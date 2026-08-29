import React, { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import type { Asset, Usage } from "./api";
import { api } from "./api";

interface Props {
  token: string;
  asset: Asset;
  onUsageChange: () => void;
}

// Plays the metered, CDN-backed variant manifest. The player requests ?position=N windows as it
// plays; the server meters each granted window and returns 402 when the plan allowance is spent.
export function Player({ token, asset, onUsageChange }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [status, setStatus] = useState<string>("idle");
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setError(null);
    setStatus("requesting session...");
    try {
      const session = await api.createSession(token, asset.asset_id);
      const url = session.manifest_url;
      const audio = audioRef.current!;
      if (Hls.isSupported()) {
        const hls = new Hls({ lowLatencyMode: false, backBufferLength: 30 });
        hlsRef.current = hls;
        hls.loadSource(url);
        hls.attachMedia(audio);
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          setStatus("playing");
          audio.play().catch(() => setStatus("ready (press play)"));
          onUsageChange();
        });
        hls.on(Hls.Events.ERROR, (_e, data) => {
          if (data.fatal) {
            if (data.response && data.response.code === 402) {
              setError("Quota exhausted — upgrade your plan to keep listening.");
              setStatus("blocked");
            } else {
              setError(`Playback error: ${data.details}`);
            }
          }
        });
      } else if (audio.canPlayType("application/vnd.apple.mpegurl")) {
        audio.src = url;
        audio.play();
        setStatus("playing (native HLS)");
        onUsageChange();
      }
    } catch (e: any) {
      setError(e.message);
      setStatus("error");
    }
  }

  useEffect(() => {
    return () => {
      hlsRef.current?.destroy();
    };
  }, []);

  return (
    <div className="player">
      <audio ref={audioRef} controls style={{ width: "100%" }} />
      <div className="player-row">
        <button onClick={start}>▶ Play (metered)</button>
        <span className={`status status-${status}`}>{status}</span>
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  );
}

export function UsageBar({ token }: { token: string }) {
  const [usage, setUsage] = useState<Usage | null>(null);
  const refresh = () => { api.getUsage(token).then(setUsage).catch(() => {}); };
  useEffect(refresh, [token]);
  if (!usage) return null;
  const remaining = usage.remaining_seconds;
  const pct = usage.included_seconds ? Math.min(100, (usage.consumed_seconds / usage.included_seconds) * 100) : 0;
  return (
    <div className="usage">
      <strong>Usage this period</strong>
      <div className="bar">
        <div className="bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <small>
        {Math.round(usage.consumed_seconds / 3600 * 10) / 10} h consumed ·{" "}
        {remaining === null ? "unlimited" : `${Math.round(remaining / 3600 * 10) / 10} h remaining`}
      </small>
    </div>
  );
}
