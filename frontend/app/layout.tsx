import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CalHack Real-Time Streaming",
  description: "Capture and stream audio/video to the CalHack backend in real time."
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
