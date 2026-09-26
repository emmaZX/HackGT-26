"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { Logo } from "./Logo";
import { PostModal } from "./PostModal";
import { AccountMenu } from "./AccountMenu";

/**
 * One size knob for the logo, name and date: 26px on phones, 34px at 1440 wide.
 * Change the clamp to resize the whole left block.
 */
const BRAND_SIZE = "text-[clamp(26px,2.36vw,34px)]";

export function Nav() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [today, setToday] = useState("");
  const [posting, setPosting] = useState(false);

  // Set on the client so the server render and the visitor's date never disagree
  useEffect(() => {
    setToday(new Date().toLocaleDateString("en-US", { month: "long", day: "numeric" }));
  }, []);

  function onSearch(event: FormEvent) {
    event.preventDefault();
    if (!q.trim()) return;
    router.push(`/search?q=${encodeURIComponent(q.trim())}`);
  }

  return (
    <header className="border-b border-[#c0d4ef] bg-[#f8f8ff]">
      {/* items-end: search, + and avatar share a bottom edge with the date */}
      <div className="mx-auto flex max-w-[1340px] flex-wrap items-end gap-x-[13px] gap-y-4 px-5 py-[clamp(16px,1.7vw,24px)] md:flex-nowrap">
        <div className={`min-w-0 ${BRAND_SIZE}`}>
          <Link href="/" aria-label="Recall Me Maybe home" className="block">
            <Logo />
          </Link>
          <div
            className="ml-[0.05em] mt-[0.12em] min-h-[1em] font-mulish font-semibold leading-none tracking-[-0.04em] text-[#c0d4ef]"
            suppressHydrationWarning
          >
            {today}
          </div>
        </div>

        <div className="order-last flex w-full items-end gap-[13px] md:order-none md:ml-auto md:w-auto">
          <form onSubmit={onSearch} role="search" className="min-w-0 flex-1 md:w-[clamp(260px,36vw,514px)] md:flex-none">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="search"
              aria-label="Search products or problems"
              className="block h-[42px] w-full rounded-full bg-[#ecf0fc] px-5 font-mulish text-[16px] tracking-[-0.04em] text-[#031d4e] shadow-[0_3px_6px_rgba(3,29,78,0.12)] outline-none focus:shadow-[0_0_0_3px_rgba(192,212,239,0.7)]"
            />
          </form>
          <button
            type="button"
            onClick={() => setPosting(true)}
            aria-label="Issue a post"
            className="grid h-[42px] w-[42px] shrink-0 place-items-center rounded-[8px] bg-[#c0d4ef] transition-colors hover:bg-[#adc5e8]"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="#fff" strokeWidth="3.4" strokeLinecap="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
        </div>

        {/* Same 42px height as the search bar; handles sign in / sign out */}
        <AccountMenu />
      </div>

      {posting && <PostModal onClose={() => setPosting(false)} />}
    </header>
  );
}
