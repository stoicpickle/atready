import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "AtReady | Product & Trust",
    template: "%s | AtReady",
  },
  description:
    "AtReady product, privacy, security, support, terms, and supported-surface information.",
  icons: {
    icon: "/brand/icon.png",
    shortcut: "/brand/icon.png",
  },
  robots: {
    index: false,
    follow: false,
  },
};

export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#0b172a",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
