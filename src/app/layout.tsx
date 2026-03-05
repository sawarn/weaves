import type { Metadata } from "next";
import { Exo_2, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { ThemeToggle } from "@/components/theme-toggle";

const exo2 = Exo_2({
  variable: "--font-exo2",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Weaves — Visual experiences for modern brands",
  description:
    "Weaves crafts visually rich, interactive web experiences and digital stories for modern brands.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${exo2.className} ${exo2.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        <Providers>
          <div className="fixed right-4 top-4 z-50 sm:right-6 sm:top-6">
            <ThemeToggle />
          </div>
          <div className="min-h-screen flex flex-col">
            <div className="flex-1 flex flex-col">{children}</div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
