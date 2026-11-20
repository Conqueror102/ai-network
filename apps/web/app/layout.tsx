import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// Inter variable (100–900). The design relies on intermediate weights
// (360, 425, 470, 520, 570), which only a variable font can render.
const inter = Inter({ subsets: ["latin"], display: "block", variable: "--font-inter" });

export const metadata: Metadata = {
  title: "AiNetwork — Network Smarter at Every Event",
  description:
    "An AI wingman for event networking. Two-way goal matching, double opt-in intros with silent declines, and an AI that helps you start the conversation.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#E6EDF6",
};

// Runs before first paint: adds the entrance pre-state class only when WAAPI
// exists and the visitor has not asked for reduced motion. Self-heals after 4s.
const preScript = `(function(){var d=document.documentElement;
if(!('animate' in Element.prototype))return;
if(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)return;
d.classList.add('pre');
setTimeout(function(){d.classList.remove('pre')},4000);})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The head script mutates <html class> before hydration.
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: preScript }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
