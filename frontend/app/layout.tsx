import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";

// Geist is not in next/font/google; use Inter as body and a geometric fallback.
// For display we map to a system geometric stack; if you add Geist via npm later,
// swap the variable.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});
const labelMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-label",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Oxiverse Audio — Founders talk. No reels, no editing. Just the signal.",
  description:
    "A privacy-first audio platform for founders. Record raw, we enhance to studio quality, listeners stream. Forensic watermarking protects your insights.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="light">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Geist:wght@400..700&display=swap"
          rel="stylesheet"
        />
        <style>{`:root{--font-display:'Geist',sans-serif;}`}</style>
      </head>
      <body className={`${inter.variable} ${labelMono.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
