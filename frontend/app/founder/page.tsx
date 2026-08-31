import { Landing } from "@/components/Landing";

// The "Founder Platform" Stitch screen is a duplicate of the landing marketing
// page. Reusing the same component keeps it DRY.
export default function FounderPlatformPage() {
  return (
    <div className="antialiased min-h-screen flex flex-col pt-[72px]">
      <Landing />
    </div>
  );
}
