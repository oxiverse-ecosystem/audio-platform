"use client";

import { useEffect, useRef } from "react";
import { Sidebar } from "@/components/Sidebar";
import { Player } from "@/components/Player";
import {
  Sparkles,
  Gauge,
  Rewind,
  Pause,
  FastForward,
  Volume2,
  ShieldCheck,
} from "lucide-react";

const CHAPTERS = [
  { time: "00:00", label: "Introduction", active: false },
  { time: "02:45", label: "The Monolith Breaks", active: false },
  { time: "14:22", label: "The Pivot: Event-Driven Architecture", active: true },
  { time: "28:10", label: "Security Implications", active: false },
  { time: "41:00", label: "Q&A and Closing Thoughts", active: false },
];

export default function NowPlayingPage() {
  const containerRef = useRef<HTMLDivElement>(null);

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
  }, []);

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 md:pl-sidebar p-margin-mobile md:p-margin-desktop flex flex-col xl:flex-row gap-gutter">
        {/* Player column */}
        <div className="flex-1 flex flex-col gap-stack-lg max-w-4xl">
          <header className="flex justify-between items-start">
            <div>
              <h2 className="font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface">
                The Pivot: Architecting for Scale
              </h2>
              <p className="font-body-lg text-body-lg text-on-surface-variant mt-2">
                By Sarah Jenkins, CTO at NexusData
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
            <div className="w-full h-48 sm:h-64 rounded-lg bg-surface-variant mb-stack-lg overflow-hidden relative">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                className="w-full h-full object-cover"
                src="https://lh3.googleusercontent.com/aida-public/AB6AXuAev32MudUN8YX54rGAR6tPqvZoy923VU0DWAM0isuAgcHQfEk3c5Dk6-DMB562Ew3MOIxEHHNSENvLPVRKl3F4ax_PFOtEM1Pq0ujRnX-1NXNbCwG30PqPN5TLjMgr1tr7U-blz0JpBJ9Nda7R1M_4MIjah9AlUomR70IRFzny-mfAjUZOEINP4aSuFrQatmCyZiS6nvji51cOl4sXDbdJ7dSdoFvCNi2FMEJcZFeuiO8LJzIqXj2W"
                alt="Abstract sound waves"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-surface/80 to-transparent" />
            </div>

            {/* Waveform */}
            <div ref={containerRef} className="w-full h-32 flex items-center justify-between mb-stack-md" />

            <div className="flex justify-between font-label-sm text-label-sm text-on-surface-variant mb-stack-lg">
              <span>14:22</span>
              <span>45:00</span>
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
              In this deep dive, Sarah discusses the inflection point where traditional
              monoliths break down and the architectural decisions required to transition
              to event-driven microservices securely.
            </p>
            <div className="flex flex-wrap gap-2">
              {["Architecture", "Scale", "SaaS"].map((t) => (
                <span key={t} className="bg-surface-container px-2 py-1 rounded font-label-sm text-label-sm text-on-surface-variant">
                  {t}
                </span>
              ))}
            </div>
          </div>

          <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6 shadow-sm flex-1">
            <h3 className="font-headline-md text-headline-md text-on-surface mb-4">Chapters</h3>
            <ul className="space-y-4">
              {CHAPTERS.map((c) => (
                <li key={c.label} className="flex gap-4 cursor-pointer group">
                  <span className={`font-label-sm text-label-sm mt-1 ${c.active ? "text-primary" : "text-on-surface-variant group-hover:text-primary transition-colors"}`}>
                    {c.time}
                  </span>
                  <div>
                    <p className={`font-body-md text-body-md group-hover:text-primary transition-colors ${c.active ? "text-primary font-medium" : "text-on-surface"}`}>
                      {c.label}
                    </p>
                    {c.active && (
                      <div className="w-full h-1 bg-surface-variant mt-2 rounded-full overflow-hidden">
                        <div className="w-1/2 h-full bg-primary" />
                      </div>
                    )}
                  </div>
                </li>
              ))}
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
