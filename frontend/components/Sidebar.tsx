"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import {
  Home,
  Mic,
  Settings,
  ShieldCheck,
  LogIn,
  LogOut,
  Menu,
  X,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { ThemeToggle } from "@/components/ThemeToggle";
import { cn } from "@/lib/utils";

const NAV = [
  { icon: Home, label: "Home", href: "/discovery" },
  { icon: ShieldCheck, label: "Creator Studio", href: "/creator" },
];

export function Sidebar() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleLogout = () => {
    logout();
    setMobileOpen(false);
    router.push("/login");
  };

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Lock body scroll when mobile drawer is open
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  // Close on Escape key
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const navContent = (
    <>
      <div className="flex flex-col gap-1">
        {NAV.map((item) => (
          <Link
            key={item.label}
            href={item.href}
            onClick={() => setMobileOpen(false)}
            className={cn(
              "flex items-center gap-3 px-3 py-2.5 rounded-lg font-caption text-caption transition-colors",
              pathname === item.href
                ? "bg-primary/10 text-primary font-semibold"
                : "text-on-surface-variant hover:bg-surface-container-high"
            )}
          >
            <item.icon className="w-5 h-5" strokeWidth={1.5} />
            {item.label}
          </Link>
        ))}
      </div>

      <div className="mt-auto flex flex-col gap-2 pt-6">
        <Link
          href="/new-drop"
          onClick={() => setMobileOpen(false)}
          className="flex items-center justify-center gap-2 bg-primary text-on-primary py-2.5 rounded-lg font-label-sm text-label-sm hover:bg-primary-container transition-colors"
        >
          <Mic className="w-4 h-4" strokeWidth={1.5} />
          New Drop
        </Link>
        <Link
          href="/account"
          onClick={() => setMobileOpen(false)}
          className={cn(
            "flex items-center gap-3 px-3 py-2.5 rounded-lg font-caption text-caption transition-colors",
            pathname === "/account"
              ? "bg-primary/10 text-primary font-semibold"
              : "text-on-surface-variant hover:bg-surface-container-high"
          )}
        >
          <Settings className="w-5 h-5" strokeWidth={1.5} />
          Account
        </Link>

        {/* Theme quick toggle */}
        <div className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-surface-container-low border border-outline-variant/30">
          <span className="font-caption text-caption text-on-surface-variant">
            Theme
          </span>
          <ThemeToggle />
        </div>

        <Link
          href="/account"
          onClick={() => setMobileOpen(false)}
          className="w-full mt-2 bg-surface text-on-surface border border-outline-variant py-2 rounded-lg font-label-sm text-label-sm hover:bg-surface-container-high transition-colors text-center"
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
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg font-caption text-caption text-on-surface-variant hover:bg-surface-container-high transition-colors w-full text-left"
            >
              <LogOut className="w-5 h-5" strokeWidth={1.5} />
              Log out
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            onClick={() => setMobileOpen(false)}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg font-caption text-caption text-on-surface-variant hover:bg-surface-container-high transition-colors"
          >
            <LogIn className="w-5 h-5" strokeWidth={1.5} />
            Log in
          </Link>
        )}
      </div>
    </>
  );

  return (
    <>
      {/* Mobile top navigation bar */}
      <header className="md:hidden fixed top-0 left-0 right-0 h-14 bg-surface/90 backdrop-blur-md border-b border-outline-variant/40 px-4 flex items-center justify-between z-40">
        <Link
          href="/"
          className="font-bold text-primary font-body-md text-body-md"
        >
          Oxiverse Audio
        </Link>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <button
            onClick={() => setMobileOpen(true)}
            type="button"
            className="w-9 h-9 rounded-lg flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors"
            aria-label="Open navigation menu"
          >
            <Menu className="w-5 h-5" strokeWidth={1.5} />
          </button>
        </div>
      </header>

      {/* Mobile Drawer Backdrop */}
      {mobileOpen && (
        <div
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 md:hidden animate-fadeIn"
          aria-hidden="true"
        />
      )}

      {/* Mobile Slide-over Drawer */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 w-72 max-w-[85vw] bg-surface border-r border-outline-variant/40 p-5 z-50 flex flex-col shadow-2xl md:hidden overflow-y-auto transition-transform duration-300 ease-in-out",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
        aria-label="Mobile Navigation"
      >
        <div className="flex items-center justify-between mb-8">
          <Link
            href="/"
            onClick={() => setMobileOpen(false)}
            className="font-bold text-primary font-body-md text-body-md"
          >
            Oxiverse Audio
          </Link>
          <button
            onClick={() => setMobileOpen(false)}
            type="button"
            className="w-8 h-8 rounded-lg flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors"
            aria-label="Close navigation menu"
          >
            <X className="w-5 h-5" strokeWidth={1.5} />
          </button>
        </div>

        {navContent}
      </aside>

      {/* Desktop sidebar */}
      <nav className="hidden md:flex w-sidebar flex-col bg-surface border-r border-outline-variant/40 p-5 fixed inset-y-0 left-0 z-40">
        <Link
          href="/"
          className="font-bold text-primary font-body-md text-body-md mb-8"
        >
          Oxiverse Audio
        </Link>
        {navContent}
      </nav>
    </>
  );
}
