"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Home,
  Mic,
  Settings,
  ShieldCheck,
  LogIn,
  LogOut,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";

const NAV = [
  { icon: Home, label: "Home", href: "/discovery" },
  { icon: ShieldCheck, label: "Creator Studio", href: "/creator" },
];

export function Sidebar() {
  const { user, logout } = useAuth();
  const router = useRouter();

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  return (
    <nav className="hidden md:flex w-sidebar flex-col bg-surface border-r border-outline-variant/40 p-5 fixed inset-y-0 left-0 z-40">
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
          href="/account"
          className="w-full mt-4 bg-surface text-on-surface border border-outline-variant py-2 rounded-lg font-label-sm text-label-sm hover:bg-surface-container-high transition-colors text-center"
        >
          Upgrade Plan
        </Link>
      </div>

      {/* Auth state */}
      <div className="mt-4 pt-4 border-t border-outline-variant/40">
        {user ? (
          <div className="flex flex-col gap-2">
            <div className="px-3 py-2">
              <div className="font-caption text-caption text-on-surface truncate">{user.display_name}</div>
              <div className="font-label-sm text-label-sm text-on-surface-variant truncate">{user.email}</div>
            </div>
            <button
              onClick={handleLogout}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg font-caption text-caption text-on-surface-variant hover:bg-surface-container-high transition-colors"
            >
              <LogOut className="w-5 h-5" strokeWidth={1.5} />
              Log out
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg font-caption text-caption text-on-surface-variant hover:bg-surface-container-high transition-colors"
          >
            <LogIn className="w-5 h-5" strokeWidth={1.5} />
            Log in
          </Link>
        )}
      </div>
    </nav>
  );
}
