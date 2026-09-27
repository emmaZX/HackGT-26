"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthProvider";
import { api } from "@/lib/api";
import { CITIES, getCity, getDisplayName, setCity, setDisplayName } from "@/lib/identity";
import { ProductCard } from "@/lib/types";

/** Pages listen for this so they refetch after a post lands */
export const POSTED_EVENT = "rmm:posted";

const MIN_STORY = 12; // backend ReportIn.text min_length

const labelClass = "font-raleway text-[16px] font-normal tracking-[-0.04em] text-[#031d4e]";
const inputClass =
  "mt-1 h-9 w-full rounded-full border border-[#eceef3] bg-white px-4 text-[14px] text-[#031d4e] outline-none focus:border-[#c0d4ef] focus:shadow-[0_0_0_3px_rgba(192,212,239,0.45)]";

export function PostModal({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, ready, configured } = useAuth();
  const firstField = useRef<HTMLInputElement>(null);
  const [products, setProducts] = useState<ProductCard[]>([]);
  const [name, setName] = useState("");
  const [productName, setProductName] = useState("");
  const [story, setStory] = useState("");
  const [location, setLocation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const saved = getDisplayName();
    setName(saved === "Neighbor" ? "" : saved);
    setLocation(getCity() || "");
    api.products().then((data) => setProducts(data.products)).catch(() => {});
    firstField.current?.focus();

    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const canSubmit = productName.trim().length > 0 && story.trim().length >= MIN_STORY;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || busy) return;
    setBusy(true);
    setError(null);

    const displayName = name.trim() || "Neighbor";
    const typed = productName.trim().toLowerCase();
    const match = products.find((p) => p.name.toLowerCase() === typed);

    try {
      const result = await api.report({
        ...(match ? { product_slug: match.slug } : { product_name: productName.trim() }),
        text: story.trim(),
        display_name: displayName,
        location_label: location.trim() || null,
      });
      setDisplayName(user?.displayName || displayName);
      if (location.trim()) setCity(location.trim());
      window.dispatchEvent(new Event(POSTED_EVENT));
      onClose();
      router.push(`/product/${result.product.slug}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't share your post. Try again.");
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[rgba(3,29,78,0.1)] px-4 py-10 md:py-[120px]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="post-title"
        className="relative w-full max-w-[660px] rounded-[20px] bg-white px-6 pb-9 pt-6 shadow-[0_10px_40px_rgba(3,29,78,0.12)] md:px-[72px]"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute left-7 top-7 grid h-8 w-8 place-items-center rounded-full hover:bg-[#f8f8ff] md:left-[36px] md:top-[34px]"
        >
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="#031d4e" strokeWidth="1.3" strokeLinecap="round">
            <path d="M5 5l14 14M19 5 5 19" />
          </svg>
        </button>

        <h2
          id="post-title"
          className="border-b border-[#c0d4ef] pb-1 pt-10 text-center font-raleway text-[24px] font-medium tracking-[-0.04em] text-[#031d4e] md:pt-[34px]"
        >
          Issue a post
        </h2>

        {ready && !user ? (
          <div className="mt-8 text-center">
            <p className="font-raleway text-[16px] tracking-[-0.04em] text-[#031d4e]">
              {configured ? "Sign in to share with the community" : "Posting needs sign-in, which isn't set up on this server yet"}
            </p>
            <p className="mx-auto mt-2 max-w-[380px] text-[13px] leading-relaxed text-[#627290]">
              Accounts keep reports tied to real people, which is what makes a cluster of them meaningful.
            </p>
            {configured && (
              <div className="mt-7 flex justify-center gap-3">
                <Link
                  href={`/login?next=${encodeURIComponent(pathname || "/")}`}
                  onClick={onClose}
                  className="btn-primary grid h-[52px] w-[160px] place-items-center font-raleway text-[16px] font-normal tracking-[-0.04em] !text-white"
                >
                  Sign in
                </Link>
                <Link
                  href="/signup"
                  onClick={onClose}
                  className="grid h-[52px] w-[160px] place-items-center rounded-full bg-[#f8f8ff] font-raleway text-[16px] tracking-[-0.04em] text-[#031d4e] hover:bg-[#ecf0fc]"
                >
                  Sign up
                </Link>
              </div>
            )}
          </div>
        ) : (
        <form onSubmit={submit} className="mt-8 grid gap-[12px]">
          <label className={labelClass}>
            Your name
            <input
              value={user?.displayName || name}
              readOnly
              aria-readonly="true"
              title="Posts go out under your account name"
              className={`${inputClass} cursor-default text-[#627290] focus:border-[#eceef3] focus:shadow-none`}
            />
          </label>

          <label className={labelClass}>
            Product name
            <input
              ref={firstField}
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              list="post-products"
              maxLength={200}
              required
              className={inputClass}
            />
            <datalist id="post-products">
              {products.map((p) => (
                <option key={p.slug} value={p.name} />
              ))}
            </datalist>
          </label>

          <label className={labelClass}>
            Tell us what happened
            <textarea
              value={story}
              onChange={(e) => setStory(e.target.value)}
              maxLength={4000}
              required
              className="mt-3 h-[184px] w-full resize-none rounded-[16px] border border-[#eceef3] bg-white px-4 py-3 text-[14px] leading-relaxed text-[#031d4e] outline-none focus:border-[#c0d4ef] focus:shadow-[0_0_0_3px_rgba(192,212,239,0.45)]"
            />
            {story.length > 0 && story.trim().length < MIN_STORY && (
              <span className="mt-1 block font-mulish text-xs tracking-normal text-[#627290]">
                A few more words, please. {MIN_STORY - story.trim().length} to go.
              </span>
            )}
          </label>

          <label className={labelClass}>
            Location
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              list="post-cities"
              maxLength={80}
              placeholder="City (optional)"
              className={inputClass}
            />
            <datalist id="post-cities">
              {CITIES.map((c) => (
                <option key={c.label} value={c.label} />
              ))}
            </datalist>
          </label>

          {error && <p role="alert" className="text-sm text-[#d9546a]">{error}</p>}

          <button
            type="submit"
            disabled={!canSubmit || busy}
            className="mx-auto mt-5 h-[52px] w-[240px] rounded-full bg-[#f8f8ff] font-raleway text-[16px] font-normal tracking-[-0.04em] text-[#031d4e] transition-colors hover:bg-[#ecf0fc] disabled:cursor-not-allowed disabled:text-[#c0d4ef] disabled:hover:bg-[#f8f8ff]"
          >
            {busy ? "Sharing…" : "Share with community"}
          </button>
        </form>
        )}
      </div>
    </div>
  );
}
