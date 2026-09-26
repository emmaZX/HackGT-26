"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { useAuth } from "@/lib/AuthProvider";
import { Logo } from "./Logo";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/explore", label: "Browse" },
  { href: "/search", label: "Look up" },
  { href: "/report", label: "Tell us" },
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, ready, logout } = useAuth();
  const [q, setQ] = useState("");

  function onSearch(event: FormEvent) {
    event.preventDefault();
    if (!q.trim()) return;
    router.push(`/search?q=${encodeURIComponent(q.trim())}`);
  }

  return (
    <header className="sticky top-0 z-30 border-b border-[#e4d9c8]/80 bg-[#f6f1e8]/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-5 py-4">
        <Link href="/" className="shrink-0">
          <Logo compact />
        </Link>
        <nav className="hidden items-center gap-5 text-sm md:flex">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={pathname === link.href ? "font-semibold text-[#1a365d]" : "text-[#5a6d80] hover:text-[#1a365d]"}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <form onSubmit={onSearch} className="ml-auto flex min-w-0 flex-1 justify-end">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Look up a product or a problem"
            className="field w-full max-w-md rounded-full"
          />
        </form>
        <div className="hidden shrink-0 items-center gap-3 md:flex">
          {ready && user ? (
            <>
              <span className="max-w-[8rem] truncate text-sm text-[#1a365d]">{user.displayName}</span>
              <button type="button" onClick={() => logout()} className="btn-soft px-3 py-2 text-sm">
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link href={`/login?next=${encodeURIComponent(pathname || "/")}`} className="text-sm text-[#5a6d80]">
                Sign in
              </Link>
              <Link href="/signup" className="btn-soft px-3 py-2 text-sm">
                Sign up
              </Link>
            </>
          )}
          <Link href="/report" className="btn-primary px-4 py-2 text-sm">
            Tell us what happened
          </Link>
        </div>
      </div>
      <div className="mx-auto flex max-w-6xl items-center gap-4 overflow-x-auto px-5 pb-3 text-sm md:hidden">
        {LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={pathname === link.href ? "font-semibold text-[#1a365d]" : "text-[#5a6d80]"}
          >
            {link.label}
          </Link>
        ))}
        {ready && user ? (
          <button type="button" onClick={() => logout()} className="ml-auto text-[#5a6d80]">
            Sign out
          </button>
        ) : (
          <Link href="/login" className="ml-auto text-[#5a6d80]">
            Sign in
          </Link>
        )}
      </div>
    </header>
  );
}
