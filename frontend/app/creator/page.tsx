import { Sidebar } from "@/components/Sidebar";
import {
  Headphones,
  User,
  Banknote,
  CreditCard,
  TrendingUp,
  Landmark,
} from "lucide-react";

const STATS = [
  { label: "Total Listens", value: "1.2M", delta: "+14% this month", icon: Headphones, up: true },
  { label: "Listeners (MTD)", value: "45.8K", delta: "+5% this month", icon: User, up: true },
  { label: "Total Earnings", value: "$12.4K", delta: "Consistent with last month", icon: Banknote, up: false },
  { label: "Pack Subscribers", value: "1,024", delta: "+22 new this week", icon: CreditCard, up: true },
];

const BARS = [
  { day: "Mon", pct: 45, val: "4.5k", active: false },
  { day: "Tue", pct: 60, val: "6.0k", active: false },
  { day: "Wed", pct: 85, val: "8.5k", active: true },
  { day: "Thu", pct: 50, val: "5.0k", active: false },
  { day: "Fri", pct: 70, val: "7.0k", active: false },
  { day: "Sat", pct: 95, val: "9.5k", active: false },
  { day: "Sun", pct: 30, val: "3.0k", active: false },
];

export default function CreatorDashboardPage() {
  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-margin-mobile md:p-margin-desktop md:pl-sidebar">
        <div className="max-w-container-max mx-auto space-y-stack-lg">
          <header className="flex justify-between items-end pb-stack-md border-b border-outline-variant/50">
            <div>
              <h2 className="font-headline-lg-mobile md:font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface mb-2">
                Creator Analytics
              </h2>
              <p className="font-body-md text-body-md text-on-surface-variant">Your pack performance and earnings overview.</p>
            </div>
            <div className="hidden sm:block">
              <span className="bg-secondary-fixed text-on-secondary-fixed px-3 py-1 rounded-full font-label-sm text-label-sm uppercase">
                Pro Creator
              </span>
            </div>
          </header>

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

          {/* Chart */}
          <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm">
            <div className="flex justify-between items-center mb-6">
              <h3 className="font-headline-md text-headline-md text-on-surface">Listens Over Time</h3>
              <select className="bg-surface-container-low border-outline-variant/50 text-on-surface text-sm rounded-md py-1 px-3 focus:border-primary focus:ring-primary font-caption">
                <option>Last 7 Days</option>
                <option>Last 30 Days</option>
                <option>All Time</option>
              </select>
            </div>
            <div className="h-64 flex items-end gap-2 sm:gap-4 mt-8 relative">
              <div className="absolute left-0 top-0 bottom-8 flex flex-col justify-between text-xs text-outline font-label-sm w-12 border-r border-outline-variant/30 pr-2 text-right hidden sm:flex">
                <span>10k</span>
                <span>7.5k</span>
                <span>5k</span>
                <span>2.5k</span>
                <span>0</span>
              </div>
              <div className="flex-1 flex items-end justify-between h-full pl-0 sm:pl-16 pb-8 relative">
                <div className="absolute inset-0 pl-0 sm:pl-16 flex flex-col justify-between pointer-events-none">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <div key={i} className={`w-full border-t border-outline-variant/20 h-0 ${i === 4 ? "border-outline-variant/50 mt-auto" : ""}`} />
                  ))}
                </div>
                <div className="flex justify-between items-end h-full z-10 flex-1">
                  {BARS.map((b) => (
                    <div key={b.day} className="flex flex-col items-center w-1/7 group h-full justify-end">
                      <div
                        className={`w-8 sm:w-12 ${b.active ? "bg-primary" : "bg-primary-fixed-dim"} rounded-t-sm relative`}
                        style={{ height: `${b.pct}%` }}
                      >
                        <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-on-surface text-surface text-xs py-1 px-2 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap font-caption">
                          {b.val}
                        </div>
                      </div>
                      <span className={`text-xs mt-2 font-label-sm ${b.active ? "text-primary font-bold" : "text-outline"}`}>{b.day}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Bottom: payout + pricing */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-gutter pb-stack-lg">
            <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm flex flex-col justify-between">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Landmark className="text-outline w-5 h-5" strokeWidth={1.5} />
                  <h3 className="font-caption text-caption text-on-surface-variant uppercase tracking-wide">Next Payout</h3>
                </div>
                <div className="font-display-lg text-display-lg text-on-surface">$2,450.00</div>
                <p className="font-body-md text-body-md text-on-surface-variant mt-1">Scheduled for Oct 1st, 2024</p>
              </div>
              <div className="mt-6 flex items-center justify-between p-4 bg-surface-container-low rounded-lg border border-outline-variant/30">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-surface-container flex items-center justify-center">
                    <span className="text-outline text-xs">💳</span>
                  </div>
                  <div>
                    <p className="font-caption text-caption text-on-surface">Stripe Standard</p>
                    <p className="font-label-sm text-label-sm text-outline">Ending in •••• 4242</p>
                  </div>
                </div>
                <span className="bg-secondary-fixed-dim/50 text-on-secondary-fixed-variant px-2 py-1 rounded text-xs font-label-sm uppercase">Active</span>
              </div>
            </div>

            <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/50 shadow-sm relative overflow-hidden">
              <h3 className="font-headline-md text-headline-md text-on-surface mb-2 relative z-10">Creator Pack Pricing</h3>
              <p className="font-body-md text-body-md text-on-surface-variant mb-6 relative z-10">
                Adjust the monthly subscription price for your premium audio packs.
              </p>
              <div className="space-y-4 relative z-10">
                <div>
                  <label className="block font-label-sm text-label-sm text-on-surface-variant uppercase mb-1" htmlFor="price">
                    Monthly Price (USD)
                  </label>
                  <div className="relative mt-1 rounded-md shadow-sm">
                    <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                      <span className="text-outline font-body-md">$</span>
                    </div>
                    <input
                      className="block w-full rounded-md border-outline-variant/50 pl-7 py-3 text-on-surface focus:border-primary focus:ring-primary sm:text-sm bg-surface-container-lowest font-body-md font-medium"
                      id="price"
                      name="price"
                      placeholder="9.99"
                      type="number"
                      defaultValue="9.99"
                    />
                  </div>
                  <p className="mt-2 text-sm text-outline font-caption flex items-center gap-1">
                    Suggested range: $5 - $15/mo based on your audience.
                  </p>
                </div>
                <div className="pt-4 border-t border-outline-variant/30 flex justify-end gap-3">
                  <button className="px-4 py-2 bg-surface-container text-on-surface rounded-md font-caption text-caption hover:bg-surface-container-high transition-colors">Cancel</button>
                  <button className="px-4 py-2 bg-primary text-on-primary rounded-md font-caption text-caption hover:bg-primary/90 transition-colors shadow-sm">Save Changes</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
