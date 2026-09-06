"use client";

import { ReactNode } from "react";
import { AuthProvider } from "@/context/AuthContext";
import { AudioPlayerProvider } from "@/context/AudioPlayerContext";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <AudioPlayerProvider>{children}</AudioPlayerProvider>
    </AuthProvider>
  );
}
