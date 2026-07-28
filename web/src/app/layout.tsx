import type { Metadata } from "next";
import { DM_Sans, Fraunces } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { SampleDataBanner } from "@/components/sample-data-banner";
import { loadMetadata } from "@/lib/data";

const sans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
});

const display = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
});

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "Field Forecast | NFL Fantasy Projections",
    template: "%s | Field Forecast",
  },
  description:
    "Open, reproducible NFL fantasy football projections for the 2026 season built on free nflverse data.",
  openGraph: {
    title: "Field Forecast",
    description: "Open NFL fantasy projections for the 2026 season.",
    type: "website",
    url: siteUrl,
  },
  twitter: {
    card: "summary_large_image",
    title: "Field Forecast",
    description: "Open NFL fantasy projections for the 2026 season.",
  },
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const meta = await loadMetadata();
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${sans.variable} ${display.variable} min-h-screen antialiased`}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <SampleDataBanner dataMode={meta?.dataMode} />
          <SiteHeader />
          <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
            {children}
          </main>
          <SiteFooter meta={meta} />
        </ThemeProvider>
      </body>
    </html>
  );
}
