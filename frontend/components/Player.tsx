import Link from "next/link";
import { PlayCircle, Volume2 } from "lucide-react";

// Persistent bottom audio player (static placeholder matching Stitch design).
export function Player() {
  return (
    <div className="fixed bottom-0 left-0 right-0 h-16 bg-surface-container-lowest/80 backdrop-blur-[12px] border-t border-outline-variant/40 z-50 flex items-center justify-between px-margin-desktop md:pl-sidebar transition-all">
      <Link href="/now-playing" className="flex items-center gap-4">
        <PlayCircle className="w-8 h-8 text-outline cursor-pointer hover:text-primary transition-colors" strokeWidth={1.5} />
        <div className="flex flex-col">
          <span className="font-caption text-caption text-on-surface">Select an episode</span>
        </div>
      </Link>
      <div className="hidden sm:block flex-1 max-w-xl px-8">
        <div className="w-full bg-surface-container-high rounded-full h-1" />
      </div>
      <div className="flex items-center gap-4">
        <Volume2 className="w-5 h-5 text-outline cursor-pointer hover:text-primary transition-colors" strokeWidth={1.5} />
      </div>
    </div>
  );
}
