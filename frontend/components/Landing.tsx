import Link from "next/link";
import { Mic, Play, Sparkles, Lock, DollarSign, ShieldCheck, type LucideIcon } from "lucide-react";

export function Landing() {
  return (
    <>
      {/* TopNavBar */}
      <header className="fixed top-0 left-0 w-full z-50 flex justify-between items-center px-margin-desktop py-4 bg-surface/80 backdrop-blur-md border-b border-outline-variant">
        <div className="flex items-center gap-8">
          <span className="font-headline-md text-headline-md font-bold text-primary">Oxiverse Audio</span>
          <nav className="hidden md:flex gap-6">
            <Link className="font-body-md text-body-md text-primary font-bold border-b-2 border-primary pb-1" href="/discovery">Listen</Link>
            <Link className="font-body-md text-body-md text-on-surface-variant hover:text-primary transition-colors" href="/creator">For Creators</Link>
            <Link className="font-body-md text-body-md text-on-surface-variant hover:text-primary transition-colors" href="/account">Pricing</Link>
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <Link className="font-body-md text-body-md text-on-surface-variant hover:text-primary transition-colors hidden md:block" href="/account">Login</Link>
          <Link className="bg-primary text-on-primary font-body-md text-body-md px-4 py-2 rounded-lg hover:opacity-90 transition-opacity active:opacity-80" href="/account">Sign Up</Link>
        </div>
      </header>

      <main className="flex-grow">
        {/* Hero */}
        <section className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop py-24 md:py-32 flex flex-col items-center text-center">
          <div className="inline-flex items-center gap-2 bg-surface-container-low border border-outline-variant px-3 py-1 rounded-full mb-8">
            <Mic className="w-4 h-4 text-primary" strokeWidth={1.5} />
            <span className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">The Signal, Amplified</span>
          </div>
          <h1 className="font-display-lg text-display-lg text-on-surface max-w-4xl mb-6 tracking-tight">
            Founders talk.
            <br />
            No reels, no editing.
            <br />
            <span className="text-primary">Just the signal.</span>
          </h1>
          <p className="font-body-lg text-body-lg text-on-surface-variant max-w-2xl mb-12">
            Your raw voice notes, instantly enhanced to studio quality. Private by design, forensic-watermarked, and creator-owned.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 w-full sm:w-auto">
            <Link className="bg-primary text-on-primary font-body-md text-body-md px-8 py-3 rounded-lg hover:bg-on-primary-fixed transition-colors shadow-sm flex items-center justify-center gap-2" href="/discovery">
              <Play className="w-5 h-5" strokeWidth={1.5} />
              Start listening
            </Link>
            <Link className="bg-surface-container-lowest text-on-surface border border-outline-variant font-body-md text-body-md px-8 py-3 rounded-lg hover:border-primary hover:text-primary transition-colors flex items-center justify-center gap-2" href="/new-drop">
              <Mic className="w-5 h-5" strokeWidth={1.5} />
              I&apos;m a founder
            </Link>
          </div>
        </section>

        {/* Features */}
        <section className="bg-surface-container-low py-24">
          <div className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <Feature icon={Sparkles} title="Auto Studio Edit" body="AI-driven noise removal and leveling instantly transforms raw thoughts into broadcast-ready audio." />
              <Feature icon={Lock} title="Private by Design" body="Encrypted streams and forensic watermarking ensure your proprietary insights stay protected." />
              <Feature icon={DollarSign} title="Creator Earns" body="Direct listener support model. You own the audience and keep the majority of the revenue." />
            </div>
          </div>
        </section>

        {/* How It Works */}
        <section className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop py-24">
          <div className="text-center mb-16">
            <h2 className="font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface mb-4">The Process</h2>
            <p className="font-body-md text-body-md text-on-surface-variant max-w-xl mx-auto">Zero friction from thought to broadcast.</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-12 relative">
            <Step icon={Mic} title="Record raw" body="Founders drop voice notes" />
            <Step icon={Sparkles} title="We enhance" body="AI studio processing" />
            <Step icon={ShieldCheck} title="Listeners stream" body="Studio-quality audio" />
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="w-full py-stack-lg px-margin-desktop flex justify-between items-center bg-surface border-t border-outline-variant">
        <div className="font-bold text-primary font-body-md text-body-md">Oxiverse Audio</div>
        <div className="font-caption text-caption text-on-surface-variant">© 2024 Oxiverse Audio. OCL License Protected.</div>
        <nav className="flex gap-4">
          {["Privacy", "Security", "API", "Terms"].map((l) => (
            <Link key={l} className="font-caption text-caption text-on-surface-variant hover:underline opacity-80" href={l === "API" ? "/account" : "/account"}>{l}</Link>
          ))}
        </nav>
      </footer>
    </>
  );
}

function Feature({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string; }) {
  return (
    <div className="bg-surface-container-lowest p-8 rounded-xl border border-outline-variant shadow-sm hover:border-primary/50 transition-colors">
      <div className="w-12 h-12 bg-secondary-container rounded-lg flex items-center justify-center mb-6">
        <Icon className="w-6 h-6 text-primary" strokeWidth={1.5} />
      </div>
      <h3 className="font-headline-md text-headline-md text-on-surface mb-3">{title}</h3>
      <p className="font-body-md text-body-md text-on-surface-variant">{body}</p>
    </div>
  );
}

function Step({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string; }) {
  return (
    <div className="relative z-10 flex flex-col items-center text-center">
      <div className="w-24 h-24 bg-surface border-2 border-primary rounded-full flex items-center justify-center mb-6 shadow-sm">
        <Icon className="w-10 h-10 text-primary" strokeWidth={1.5} />
      </div>
      <h4 className="font-headline-md text-headline-md text-on-surface mb-2">{title}</h4>
      <p className="font-body-md text-body-md text-on-surface-variant">{body}</p>
    </div>
  );
}
