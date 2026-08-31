import Link from "next/link";
import {
  Home,
  Users,
  LibraryBig,
  Wallet,
  Mic,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { icon: Home, label: "Home", href: "/discovery" },
  { icon: Users, label: "Following", href: "/discovery" },
  { icon: LibraryBig, label: "Creator Packs", href: "/account" },
  { icon: Wallet, label: "Library", href: "/discovery" },
];

export function Sidebar() {
  return (
    <nav className="hidden md:flex flex-col w-64 flex-shrink-0 bg-surface-container border-r border-outline-variant/30 p-margin-desktop overflow-y-auto hide-scrollbar">
      <Link
        href="/"
        className="font-bold text-primary font-body-md text-body-md mb-8"
      >
        Oxiverse Audio
      </Link>
      <div className="flex flex-col gap-1">
        {NAV.map((item) => (
          <Link
            key={item.label}
            href={item.href}
            className={cn(
              "flex items-center gap-3 px-3 py-2.5 rounded-lg font-caption text-caption text-on-surface-variant hover:bg-surface-container-high transition-colors"
            )}
          >
            <item.icon className="w-5 h-5" strokeWidth={1.5} />
            {item.label}
          </Link>
        ))}
      </div>

      <div className="mt-auto flex flex-col gap-2">
        <Link
          href="/new-drop"
          className="flex items-center justify-center gap-2 bg-primary text-on-primary py-2.5 rounded-lg font-label-sm text-label-sm hover:bg-primary-container transition-colors"
        >
          <Mic className="w-4 h-4" strokeWidth={1.5} />
          New Drop
        </Link>
        <Link
          href="/account"
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg font-caption text-caption text-on-surface-variant hover:bg-surface-container-high transition-colors"
        >
          <Settings className="w-5 h-5" strokeWidth={1.5} />
          Account
        </Link>
        <Link
          href="/creator"
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg font-caption text-caption text-on-surface-variant hover:bg-surface-container-high transition-colors"
        >
          <ShieldCheck className="w-5 h-5" strokeWidth={1.5} />
          Creator
        </Link>
        <Link
          href="/account"
          className="w-full mt-4 bg-surface text-on-surface border border-outline-variant py-2 rounded-lg font-label-sm text-label-sm hover:bg-surface-container-high transition-colors text-center"
        >
          Upgrade Plan
        </Link>
      </div>
    </nav>
  );
}
