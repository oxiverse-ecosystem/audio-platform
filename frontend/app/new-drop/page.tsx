import { Sidebar } from "@/components/Sidebar";
import {
  CloudUpload,
  CheckCircle,
  Globe,
  Lock,
  Play,
} from "lucide-react";

export default function NewDropPage() {
  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-grow overflow-y-auto bg-surface-bright relative">
        <div className="max-w-container-max mx-auto px-margin-desktop py-stack-lg">
          <header className="mb-stack-lg flex justify-between items-end">
            <div>
              <h2 className="font-headline-lg text-headline-lg text-on-surface">New Drop</h2>
              <p className="font-body-md text-body-md text-on-surface-variant mt-2">
                Upload and enhance your audio for the Oxiverse network.
              </p>
            </div>
            <button className="bg-primary text-on-primary px-6 py-3 rounded-lg font-caption text-caption hover:bg-primary-container transition-colors shadow-sm">
              Publish to Oxiverse
            </button>
          </header>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
            {/* Left: Upload + processing */}
            <div className="lg:col-span-7 flex flex-col gap-stack-lg">
              <div className="border-2 border-dashed border-outline-variant bg-surface rounded-xl p-stack-lg flex flex-col items-center justify-center text-center transition-colors hover:border-primary hover:bg-surface-container-low cursor-pointer min-h-[240px]">
                <CloudUpload className="w-10 h-10 text-on-surface-variant mb-4" strokeWidth={1.5} />
                <h3 className="font-headline-md text-headline-md text-on-surface mb-2">Drag &amp; Drop Audio</h3>
                <p className="font-body-md text-body-md text-on-surface-variant mb-6">WAV, MP3, or FLAC up to 500MB</p>
                <button className="bg-surface-container-lowest border border-outline-variant text-on-surface px-4 py-2 rounded-lg font-caption text-caption hover:border-primary transition-colors">
                  Browse Files
                </button>
              </div>

              {/* Processing stepper */}
              <div className="bg-surface-container-lowest border border-outline-variant rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
                <h4 className="font-caption text-caption text-on-surface font-bold mb-6">Processing Pipeline</h4>
                <div className="relative pl-8 border-l-2 border-primary pb-8">
                  <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full bg-primary ring-4 ring-surface-container-lowest" />
                  <h5 className="font-caption text-caption text-on-surface">1. Uploaded</h5>
                  <p className="font-label-sm text-label-sm text-on-surface-variant mt-1">founders_update_v2.wav (42MB)</p>
                  <CheckCircle className="text-primary w-4 h-4 mt-2" strokeWidth={1.5} />
                </div>
                <div className="relative pl-8 border-l-2 border-surface-variant pb-8">
                  <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full border-2 border-primary bg-surface-container-lowest ring-4 ring-surface-container-lowest flex items-center justify-center">
                    <div className="w-2 h-2 bg-primary rounded-full animate-pulse" />
                  </div>
                  <h5 className="font-caption text-caption text-on-surface font-bold">2. Repairing</h5>
                  <p className="font-label-sm text-label-sm text-on-surface-variant mt-1">Removing background noise and hum.</p>
                  <div className="w-full bg-surface-variant rounded-full h-1.5 mt-4 overflow-hidden">
                    <div className="bg-primary h-1.5 rounded-full w-[45%] transition-all duration-1000" />
                  </div>
                </div>
                <div className="relative pl-8 border-l-2 border-surface-variant pb-8 opacity-50">
                  <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full border-2 border-outline-variant bg-surface-container-lowest ring-4 ring-surface-container-lowest" />
                  <h5 className="font-caption text-caption text-on-surface">3. Enhancing to Studio</h5>
                  <p className="font-label-sm text-label-sm text-on-surface-variant mt-1">Applying Oxiverse EQ and compression.</p>
                </div>
                <div className="relative pl-8 opacity-50">
                  <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full border-2 border-outline-variant bg-surface-container-lowest ring-4 ring-surface-container-lowest" />
                  <h5 className="font-caption text-caption text-on-surface">4. Ready</h5>
                </div>
              </div>
            </div>

            {/* Right: metadata */}
            <div className="lg:col-span-5 flex flex-col gap-stack-lg">
              <div className="bg-surface-container-lowest border border-outline-variant rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] flex flex-col gap-stack-md">
                <div>
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-2">EPISODE TITLE</label>
                  <input
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3 font-caption text-caption text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all"
                    type="text"
                    defaultValue="Q3 Strategy & Market Adjustments"
                  />
                </div>
                <div>
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-2">DESCRIPTION</label>
                  <textarea
                    className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3 font-caption text-caption text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all resize-none"
                    rows={4}
                    defaultValue="A brief overview of our shifting priorities for Q3, focusing on lean operations and extending runway."
                  />
                </div>
                <div className="pt-4 border-t border-outline-variant">
                  <label className="block font-label-sm text-label-sm text-on-surface-variant mb-4">VISIBILITY</label>
                  <div className="flex gap-4">
                    <label className="flex-1 cursor-pointer">
                      <input className="peer sr-only" name="visibility" type="radio" />
                      <div className="border border-outline-variant rounded-lg p-4 text-center peer-checked:border-primary peer-checked:bg-secondary-container transition-colors">
                        <Globe className="w-6 h-6 mb-2 text-on-surface-variant mx-auto" strokeWidth={1.5} />
                        <p className="font-caption text-caption text-on-surface">Public</p>
                      </div>
                    </label>
                    <label className="flex-1 cursor-pointer">
                      <input defaultChecked className="peer sr-only" name="visibility" type="radio" />
                      <div className="border border-outline-variant rounded-lg p-4 text-center border-primary bg-secondary-container transition-colors">
                        <Lock className="w-6 h-6 mb-2 text-primary mx-auto" strokeWidth={1.5} />
                        <p className="font-caption text-caption text-on-surface font-bold">Creator-Pack Only</p>
                      </div>
                    </label>
                  </div>
                </div>
                <div className="pt-4">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input defaultChecked className="w-5 h-5 text-primary bg-surface-container-low border-outline-variant rounded" type="checkbox" />
                    <span className="font-caption text-caption text-on-surface">Set as part of your active pack</span>
                  </label>
                </div>
              </div>

              {/* Audio preview */}
              <div className="bg-surface-container-low border border-outline-variant rounded-xl p-6 relative overflow-hidden">
                <div className="absolute inset-0 opacity-20 pointer-events-none" style={{ background: "linear-gradient(135deg, rgba(70,72,212,0.1) 0%, rgba(218,226,253,0.1) 100%)", backdropFilter: "blur(10px)" }} />
                <h4 className="font-caption text-caption text-on-surface font-bold mb-4 relative z-10">Enhancement Preview</h4>
                <div className="flex items-center gap-4 relative z-10 bg-surface-container-lowest p-4 rounded-lg border border-outline-variant">
                  <button className="w-10 h-10 rounded-full bg-primary text-on-primary flex items-center justify-center hover:bg-primary-container transition-colors flex-shrink-0">
                    <Play className="w-5 h-5" strokeWidth={1.5} />
                  </button>
                  <div className="flex-grow h-10 relative">
                    <div className="absolute inset-0 rounded bg-surface-variant" />
                    <div className="absolute inset-y-0 left-0 w-[60%] rounded bg-primary-fixed-dim" />
                  </div>
                  <span className="font-label-sm text-label-sm text-on-surface-variant flex-shrink-0">0:14 / 2:35</span>
                </div>
                <div className="flex justify-center mt-4 relative z-10">
                  <div className="inline-flex bg-surface-container-lowest rounded-lg border border-outline-variant p-1">
                    <button className="px-4 py-1.5 rounded-md font-caption text-caption text-on-surface-variant hover:bg-surface-variant transition-colors">Original</button>
                    <button className="px-4 py-1.5 rounded-md font-caption text-caption bg-surface-variant text-on-surface font-bold shadow-sm">Studio Enhanced</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
