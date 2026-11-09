import type { Metadata } from "next";
import { IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

const plex = IBM_Plex_Mono({
  variable: "--font-plex",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Stock Portfolio Agent",
  description: "Watch an AI agent analyze a stock portfolio step by step.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // "dark" switches the CopilotKit chat to its dark theme.
    <html lang="en" className={`${plex.variable} dark h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
