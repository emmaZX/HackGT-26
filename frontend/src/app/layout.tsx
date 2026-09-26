import type { Metadata } from "next";
import { Mulish, Raleway } from "next/font/google";
import { Nav } from "@/components/Nav";
import { Disclaimer } from "@/components/Disclaimer";
import { Providers } from "@/components/Providers";
import "./globals.css";

const raleway = Raleway({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-raleway-next",
});

const mulish = Mulish({
  subsets: ["latin"],
  weight: ["300", "400", "600", "700"],
  variable: "--font-mulish-next",
});

export const metadata: Metadata = {
  title: "Recall Me Maybe",
  description: "See official recalls and what people nearby are noticing about everyday products.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${raleway.variable} ${mulish.variable}`}>
      <body className="antialiased">
        <Providers>
          <Nav />
          <main className="mx-auto min-h-[70vh] max-w-[1340px] px-5 pb-12 pt-8 md:pt-9">{children}</main>
          <footer className="mx-auto max-w-[1340px] px-5 pb-12">
            <Disclaimer />
          </footer>
        </Providers>
      </body>
    </html>
  );
}
