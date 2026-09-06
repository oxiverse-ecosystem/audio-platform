"use client";

import { ReactNode } from "react";
import { ThemeProvider } from "@/context/ThemeContext";
import { AuthProvider } from "@/context/AuthContext";
import { AudioPlayerProvider } from "@/context/AudioPlayerContext";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AudioPlayerProvider>{children}</AudioPlayerProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
