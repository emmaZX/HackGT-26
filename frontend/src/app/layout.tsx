import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import { Disclaimer } from "@/components/Disclaimer";
import { Decor } from "@/components/Decor";
import { Providers } from "@/components/Providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Recall Me Maybe — Product safety, made neighborly",
  description: "See official recalls and what people nearby are noticing about everyday products.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="relative antialiased">
        <Providers>
          <Decor />
          <Nav />
          <main className="mx-auto min-h-[70vh] max-w-6xl px-5 py-8">{children}</main>
          <footer className="mx-auto max-w-6xl px-5 pb-12">
            <Disclaimer />
          </footer>
        </Providers>
      </body>
    </html>
  );
}
