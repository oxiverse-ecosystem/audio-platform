import Link from "next/link";
import { Search, Lock, Clock, Play, Bolt } from "lucide-react";
import { Sidebar } from "@/components/Sidebar";
import { Player } from "@/components/Player";

const EPISODES = [
  {
    creator: "Naval R.",
    time: "2h ago",
    pack: true,
    title: "The Signal vs. Noise in AI",
    duration: "14:02",
    plays: "12.4k",
    img: "https://lh3.googleusercontent.com/aida-public/AB6AXuC-qhAIMPusmYmAAFuVux1GrGP8MxfGlQ94WXmWtTnOdEIBosOzzvv8jvf-B6ENBw8Bqq4NoAIODDd0dnh4vE-X8cL2QXONClNSfXTIkL56S4djjeJX4mAluduXtw8Eb1np-7nmv_7D-ZYRgRxo0u8_UNqJeIDh2ArOydNpayPEQ81fp_1JlcbiiZCDD6x7gMsoGk-hwy4HyHRO9C9CuyXQKTb_fm7uofLDwe3uqy4D9FLlQgD1OhN1",
    span: "",
  },
  {
    creator: "Sarah T.",
    time: "5h ago",
    pack: false,
    title: "SaaS Valuations in Q3",
    duration: "28:45",
    plays: "8.1k",
    img: "https://lh3.googleusercontent.com/aida-public/AB6AXuAq8PZS_HkvhwF3R84hwllUJf2IbfCDXdueD-ek2bX7_H4HH0VbRgaQXXLKA-NOENbt8LdTMHdwDUA6ZdH9IoW-sfrbp9FcgrkNT12Q3JBCshNuLe0AtMVSquicCu2thMAQqwTI242xArq8Q8RdtnXxwet-zdtVxBVF7a8LmtzNepdoEDD_xixrtRDJ4w6PZqzbBp7ZiyelmUdLmy9M4lUlVypW_pSOmOXeVXTkOIVY60faPA3Eje2n",
    span: "",
  },
  {
    creator: "a16z Audio",
    time: "1d ago",
    pack: false,
    title: "Building the Decentralized Web",
    duration: "45:10",
    plays: "42k",
    desc: "A deep dive into the infrastructure requirements for the next iteration of internet protocols.",
    img: "https://lh3.googleusercontent.com/aida-public/AB6AXuBOP-Pc6XGe_V-bfEERA67fjQRtH1WNufFrH9FEuoYq49oaU19QB4scCS-bXLUdH9jN5I8YhgX5x1WB0-9Bpa_Ep1Pvc5fwkGStJu57a8SJfW8njKj5KQ-KvR78dn1lritlom4YnMgiM9gQRDuJdcaVnHJ64aGGbRDyb8WFfFkYsuV1VoAG1hP4uaJJkRCgMqXbT_7OJ1U_quxHzDqWg0EpmQ3d1eYVO1vEVC92bLkYSj32DSTfJfLo",
    span: "lg:col-span-2",
  },
];

export default function DiscoveryPage() {
  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 flex flex-col md:flex-row min-w-0 overflow-hidden">
        {/* Center Canvas */}
        <div className="flex-1 overflow-y-auto px-margin-mobile md:px-margin-desktop py-stack-lg hide-scrollbar">
          <div className="max-w-container-max mx-auto mb-stack-lg">
            <div className="relative w-full max-w-2xl">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-outline w-5 h-5" strokeWidth={1.5} />
              <input
                className="w-full bg-surface-container-lowest border border-outline-variant/50 rounded-xl py-3 pl-12 pr-4 font-label-sm text-label-sm text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all shadow-sm"
                placeholder="Search episodes, creators, or topics..."
                type="text"
              />
            </div>
            <div className="flex flex-wrap gap-2 mt-stack-md">
              <button className="bg-primary text-on-primary px-4 py-1.5 rounded-full font-label-sm text-label-sm">
                Newest
              </button>
              {["Following", "By Creator", "Popular"].map((f) => (
                <button
                  key={f}
                  className="bg-surface-container border border-outline-variant/30 text-on-surface px-4 py-1.5 rounded-full font-label-sm text-label-sm hover:bg-surface-container-high transition-colors"
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          <div className="max-w-container-max mx-auto grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-gutter">
            {EPISODES.map((ep) => (
              <EpisodeCard key={ep.title} ep={ep} />
            ))}
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
              <div className="flex gap-3 items-center group cursor-pointer">
                <div className="w-12 h-12 rounded bg-surface-container-high flex-shrink-0 flex items-center justify-center group-hover:bg-secondary-container transition-colors">
                  <span className="text-outline group-hover:text-primary">▶</span>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-caption text-caption text-on-surface truncate">The Bootstrapper&apos;s Guide</p>
                  <p className="font-label-sm text-label-sm text-outline truncate">12 mins</p>
                </div>
              </div>
            </div>
          </div>
        </aside>
      </main>
      <Player />
    </div>
  );
}

function EpisodeCard({ ep }: { ep: (typeof EPISODES)[number] }) {
  return (
    <Link href="/now-playing" className={`bg-surface-container-lowest rounded-[16px] border border-outline-variant/40 p-5 hover:border-primary-fixed-dim hover:shadow-[0_4px_20px_rgba(96,99,238,0.08)] transition-all group flex flex-col cursor-pointer relative overflow-hidden ${ep.span}`}>
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="w-10 h-10 rounded-full object-cover" src={ep.img} alt={ep.creator} />
          <div>
            <p className="font-caption text-caption text-on-surface font-semibold">{ep.creator}</p>
            <p className="font-label-sm text-label-sm text-outline text-[10px]">{ep.time}</p>
          </div>
        </div>
        {ep.pack && (
          <span className="bg-surface-container px-2 py-0.5 rounded text-[10px] font-label-sm text-on-surface-variant flex items-center gap-1 border border-outline-variant/20">
            <Lock className="w-3 h-3" strokeWidth={1.5} /> Pack
          </span>
        )}
      </div>
      <h3 className="font-headline-md text-headline-md font-bold mb-2 leading-tight">{ep.title}</h3>
      {ep.desc && <p className="font-body-md text-body-md text-on-surface-variant max-w-md line-clamp-2 mb-2">{ep.desc}</p>}
      <div className="mt-auto pt-4 flex items-center justify-between border-t border-outline-variant/20">
        <div className="flex items-center gap-4 text-outline font-label-sm text-label-sm">
          <span className="flex items-center gap-1">
            <Clock className="w-4 h-4" strokeWidth={1.5} /> {ep.duration}
          </span>
          <span className="flex items-center gap-1">
            <Play className="w-4 h-4" strokeWidth={1.5} /> {ep.plays}
          </span>
        </div>
        <button className="w-8 h-8 rounded-full bg-surface-container-high group-hover:bg-primary group-hover:text-on-primary flex items-center justify-center transition-colors">
          <Play className="w-[18px] h-[18px]" strokeWidth={1.5} />
        </button>
      </div>
    </Link>
  );
}
