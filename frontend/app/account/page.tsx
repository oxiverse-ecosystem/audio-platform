"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { useAuth } from "@/context/AuthContext";
import {
  Check,
  X,
  Mail,
  Shield,
  Download,
  MoreVertical,
  Plus,
  Loader2,
} from "lucide-react";

type Tab = "plan" | "usage" | "security";

export default function AccountPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("plan");

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
          <p className="font-body-md text-body-md text-on-surface-variant mb-6">Log in to view your account settings.</p>
          <Link href="/login" className="bg-primary text-on-primary font-body-md text-body-md px-6 py-2.5 rounded-lg hover:bg-on-primary-fixed transition-colors">
            Log in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 overflow-y-auto bg-surface relative md:pl-sidebar">
        <div className="max-w-container-max mx-auto p-margin-mobile md:p-margin-desktop pb-32">
          <div className="mb-stack-lg">
            <h1 className="font-headline-lg text-headline-lg hidden md:block text-on-surface mb-2">Account Settings</h1>
            <p className="font-body-md text-body-md text-on-surface-variant">
              Manage your billing, monitor usage, and configure security preferences.
            </p>
          </div>

          <div className="flex gap-4 border-b border-surface-variant mb-stack-lg overflow-x-auto">
            <TabBtn id="plan" label="Plan & Billing" tab={tab} setTab={setTab} />
            <TabBtn id="usage" label="Usage Metrics" tab={tab} setTab={setTab} />
            <TabBtn id="security" label="Security & Privacy" tab={tab} setTab={setTab} />
          </div>

          {tab === "plan" && <PlanTab />}
          {tab === "usage" && <UsageTab />}
          {tab === "security" && <SecurityTab user={user} />}
        </div>
      </main>
    </div>
  );
}

function TabBtn({ id, label, tab, setTab }: { id: Tab; label: string; tab: Tab; setTab: (t: Tab) => void }) {
  const active = tab === id;
  return (
    <button
      onClick={() => setTab(id)}
      className={`px-4 py-2 font-label-sm text-label-sm border-b-2 whitespace-nowrap transition-colors ${
        active ? "border-primary text-primary" : "border-transparent text-on-surface-variant hover:text-on-surface"
      }`}
    >
      {label}
    </button>
  );
}

function PlanTab() {
  return (
    <div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-gutter mb-stack-lg">
        <div className="bg-surface-container-lowest rounded-xl p-6 flex flex-col relative overflow-hidden border border-outline-variant/50">
          <div className="absolute top-0 left-0 w-full h-1 bg-surface-variant" />
          <div className="flex justify-between items-start mb-4">
            <div>
              <h3 className="font-headline-md text-headline-md text-on-surface">Free</h3>
              <div className="font-body-lg text-body-lg text-on-surface-variant mt-1">$0 / month</div>
            </div>
            <span className="bg-surface-container-high text-on-surface-variant px-3 py-1 rounded-full font-label-sm text-label-sm">Current</span>
          </div>
          <ul className="font-body-md text-body-md text-on-surface space-y-3 mb-8 flex-1">
            <Li ok>10 hours monthly listening</Li>
            <Li ok>Standard tracks access</Li>
            <Li bad>No watermark protection</Li>
          </ul>
          <button className="w-full bg-surface-container border border-outline-variant text-on-surface font-caption text-caption py-3 rounded-lg hover:bg-surface-variant transition-colors" disabled>
            Active Plan
          </button>
        </div>
        <div className="bg-surface-container-lowest rounded-xl p-6 flex flex-col relative border border-primary/30 shadow-[0_8px_30px_rgb(96,99,238,0.12)]">
          <div className="absolute top-0 left-0 w-full h-1 bg-primary" />
          <div className="flex justify-between items-start mb-4">
            <div>
              <h3 className="font-headline-md text-headline-md text-on-surface">Pro Platform</h3>
              <div className="font-body-lg text-body-lg text-primary mt-1">$19 <span className="text-on-surface-variant text-sm">/ month</span></div>
            </div>
          </div>
          <ul className="font-body-md text-body-md text-on-surface space-y-3 mb-8 flex-1">
            <Li ok>50 hours monthly listening</Li>
            <Li ok>Premium tracks access</Li>
            <Li ok>Advanced watermark protection</Li>
          </ul>
          <button className="w-full bg-primary text-on-primary font-caption text-caption py-3 rounded-lg hover:bg-on-primary-fixed-variant transition-colors">
            Upgrade to Pro
          </button>
        </div>
      </div>

      <div>
        <h3 className="font-headline-md text-headline-md mb-4 text-on-surface">Active Creator Packs</h3>
        <p className="font-body-md text-body-md text-on-surface-variant mb-6">
          Subscriptions providing unlimited access to specific founder archives.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="border border-dashed border-outline-variant rounded-xl p-4 flex items-center justify-center gap-2 text-on-surface-variant hover:text-primary hover:border-primary transition-colors cursor-pointer bg-surface-container-lowest/50">
            <Plus className="w-5 h-5" strokeWidth={1.5} />
            <span className="font-label-sm text-label-sm">Browse Creator Packs</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function UsageTab() {
  return (
    <div className="bg-surface-container-lowest rounded-xl p-8 max-w-3xl border border-outline-variant/50">
      <h3 className="font-headline-md text-headline-md mb-2 text-on-surface">Current Cycle Usage</h3>
      <p className="font-body-md text-body-md text-on-surface-variant mb-8">Free tier: 10 hours monthly listening</p>
      <div className="mb-4 flex justify-between items-end">
        <div className="font-display-lg text-display-lg text-primary tracking-tight">
          0 <span className="font-body-lg text-body-lg text-on-surface-variant tracking-normal">hrs</span>
        </div>
        <div className="font-label-sm text-label-sm text-on-surface-variant text-right">10 hrs limit</div>
      </div>
      <div className="w-full bg-surface-variant rounded-full h-3 mb-2 overflow-hidden relative">
        <div className="bg-primary h-3 rounded-full absolute top-0 left-0" style={{ width: "0%" }} />
        <div className="absolute top-0 w-0.5 h-full bg-on-surface/20" style={{ left: "50%" }} />
      </div>
      <div className="flex justify-between font-label-sm text-label-sm text-on-surface-variant">
        <span>0%</span>
        <span>0% utilized</span>
        <span>100%</span>
      </div>
      <div className="mt-8 pt-8 border-t border-surface-variant">
        <button className="bg-surface-container text-on-surface font-caption text-caption py-2 px-6 rounded-lg border border-outline-variant hover:bg-surface-variant transition-colors flex items-center gap-2">
          <Download className="w-4 h-4" strokeWidth={1.5} /> Export Usage Log
        </button>
      </div>
    </div>
  );
}

function SecurityTab({ user }: { user: { email: string; email_verified: boolean } }) {
  return (
    <div className="max-w-3xl space-y-stack-md">
      <div className="bg-surface-container-lowest rounded-xl p-6 border border-outline-variant/50">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-secondary-container rounded-lg text-on-secondary-container">
            <Mail className="w-5 h-5" strokeWidth={1.5} />
          </div>
          <div className="flex-1">
            <h3 className="font-caption text-caption font-semibold text-on-surface mb-1">Email</h3>
            <p className="font-body-md text-body-md text-on-surface-variant mb-4">
              Your account is secured with email + password authentication.
            </p>
            <div className="bg-surface p-3 rounded border border-outline-variant mb-4 flex items-center justify-between">
              <span className="font-label-sm text-label-sm text-on-surface">{user.email}</span>
              {user.email_verified ? (
                <span className="bg-surface-container-high text-on-surface-variant px-2 py-0.5 rounded text-[10px] uppercase tracking-wider">Verified</span>
              ) : (
                <Link href="/verify-email" className="text-primary font-label-sm text-label-sm hover:underline">Verify</Link>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-surface-container-lowest rounded-xl p-6 border border-outline-variant/50">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-surface-container-high rounded-lg text-on-surface-variant">
            <Shield className="w-5 h-5" strokeWidth={1.5} />
          </div>
          <div className="flex-1">
            <h3 className="font-caption text-caption font-semibold text-on-surface mb-1">Data &amp; Privacy</h3>
            <p className="font-body-md text-body-md text-on-surface-variant mb-6">
              Manage how Oxiverse handles your listening data.
            </p>
            <div className="flex items-center justify-between py-3 border-t border-surface-variant">
              <div>
                <div className="font-caption text-caption text-on-surface">Anonymous Analytics</div>
                <div className="font-label-sm text-label-sm text-on-surface-variant max-w-sm mt-1">
                  Help improve the platform by sending anonymous usage and crash data.
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input defaultChecked className="sr-only peer" type="checkbox" />
                <div className="w-11 h-6 bg-surface-variant peer-checked:bg-primary rounded-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-full" />
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Li({ children, ok, bad }: { children: React.ReactNode; ok?: boolean; bad?: boolean }) {
  return (
    <li className={`flex items-center gap-2 ${bad ? "text-on-surface-variant" : ""}`}>
      {ok ? (
        <Check className="text-primary w-4 h-4" strokeWidth={1.5} />
      ) : (
        <X className="text-surface-variant w-4 h-4" strokeWidth={1.5} />
      )}
      {children}
    </li>
  );
}
