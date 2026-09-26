"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/AuthProvider";

/** The navy avatar: opens sign in / sign up, or your name + sign out */
export function AccountMenu() {
  const { user, ready, logout } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const next = encodeURIComponent(pathname || "/");

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !wrap.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => setOpen(false), [pathname]);

  const item = "block w-full rounded-[10px] px-3 py-2 text-left text-[14px] tracking-[-0.02em] hover:bg-[#f8f8ff]";

  return (
    <div ref={wrap} className="relative ml-auto shrink-0 md:ml-[clamp(8px,2vw,29px)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={user ? `Account: ${user.displayName}` : "Sign in or sign up"}
        aria-expanded={open}
        aria-haspopup="menu"
        className="block h-[42px] w-[42px] overflow-hidden rounded-full bg-[#031d4e] ring-offset-2 transition-shadow hover:ring-2 hover:ring-[#c0d4ef]"
      >
        <svg viewBox="0 0 90 90" className="h-full w-full" aria-hidden>
          <circle cx="45" cy="38" r="14.5" fill="#fff" />
          <path d="M25 90V70a10 10 0 0 1 10-10h20a10 10 0 0 1 10 10v20Z" fill="#fff" />
        </svg>
      </button>

      {open && ready && (
        <div role="menu" className="card absolute right-0 top-[52px] z-40 w-[200px] p-2">
          {user ? (
            <>
              <p className="truncate px-3 pb-2 pt-1 text-[13px] text-[#627290]">
                Signed in as <span className="text-[#031d4e]">{user.displayName}</span>
              </p>
              <button role="menuitem" type="button" onClick={() => logout()} className={item}>
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link role="menuitem" href={`/login?next=${next}`} className={item}>
                Sign in
              </Link>
              <Link role="menuitem" href="/signup" className={item}>
                Sign up
              </Link>
            </>
          )}
        </div>
      )}
    </div>
  );
}
