"use client";

import { useEffect, useRef } from "react";
import { ProductCard as Product } from "@/lib/types";
import { ProductCard } from "./ProductCard";

const CARD_STEP = 365; // 335px card + 30px gap
const SPEED = 40; // px per second

/**
 * "recent updates" row: scrolls itself, loops forever, and hands control to the
 * visitor while they hover, focus, touch, or drag it.
 *
 * The card set is rendered three times. The scroll position is kept inside the
 * middle copy; whenever it drifts into the first or last copy it jumps by one
 * set width, which looks identical, so the loop never visibly restarts.
 */
export function RecentCarousel({ products }: { products: Product[] }) {
  const scroller = useRef<HTMLDivElement>(null);
  const firstCopy = useRef<HTMLDivElement>(null);
  const pos = useRef(0); // float position; browsers round scrollLeft, which would stall slow scrolling
  const hold = useRef({ hover: false, focus: false, touch: false, drag: false });
  const drag = useRef<{ x: number; left: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const touchTimer = useRef<number | undefined>(undefined);

  // Short lists repeat until one set is wider than the visible row
  const repeats = Math.max(1, Math.ceil(2400 / (products.length * CARD_STEP)));
  const set = Array.from({ length: repeats }, () => products).flat();

  const paused = () => Object.values(hold.current).some(Boolean);
  const setWidth = () => firstCopy.current?.offsetWidth || 1;

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    el.scrollLeft = setWidth();
    pos.current = el.scrollLeft;

    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (!paused() && !reduceMotion.matches) {
        const w = setWidth();
        let next = pos.current + SPEED * dt;
        if (next >= 2 * w) next -= w;
        pos.current = next;
        el.scrollLeft = next;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(touchTimer.current);
    };
  }, [set.length]);

  function onScroll() {
    const el = scroller.current!;
    const w = setWidth();
    let shift = 0;
    if (el.scrollLeft < w) shift = w;
    else if (el.scrollLeft >= 2 * w) shift = -w;
    if (shift) {
      el.scrollLeft += shift;
      if (drag.current) drag.current.left += shift;
    }
    if (shift || paused()) pos.current = el.scrollLeft;
  }

  // Mouse drag (touch and trackpads scroll natively)
  function onPointerDown(e: React.PointerEvent) {
    if (e.pointerType !== "mouse" || e.button !== 0) return;
    drag.current = { x: e.clientX, left: scroller.current!.scrollLeft, moved: false };
    hold.current.drag = true;
  }
  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    if (!d.moved && Math.abs(dx) > 5) {
      d.moved = true;
      scroller.current!.setPointerCapture(e.pointerId);
    }
    if (d.moved) scroller.current!.scrollLeft = d.left - dx;
  }
  function endDrag() {
    if (drag.current?.moved) suppressClick.current = true;
    drag.current = null;
    hold.current.drag = false;
    pos.current = scroller.current!.scrollLeft;
  }

  return (
    <div
      ref={scroller}
      onScroll={onScroll}
      onPointerEnter={(e) => e.pointerType === "mouse" && (hold.current.hover = true)}
      onPointerLeave={(e) => e.pointerType === "mouse" && (hold.current.hover = false)}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onTouchStart={() => {
        window.clearTimeout(touchTimer.current);
        hold.current.touch = true;
      }}
      onTouchEnd={() => {
        touchTimer.current = window.setTimeout(() => (hold.current.touch = false), 2000);
      }}
      onFocus={() => (hold.current.focus = true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) hold.current.focus = false;
      }}
      onClickCapture={(e) => {
        if (suppressClick.current) {
          e.preventDefault();
          e.stopPropagation();
          suppressClick.current = false;
        }
      }}
      onDragStart={(e) => e.preventDefault()}
      className="no-scrollbar cursor-grab select-none overflow-x-auto overflow-y-hidden pb-[18px] pt-[15px] active:cursor-grabbing"
    >
      <div className="flex w-max">
        {[0, 1, 2].map((copy) => (
          <div key={copy} ref={copy === 0 ? firstCopy : undefined} className="flex">
            {set.map((product, i) => {
              // Only the first run of the middle copy is exposed to keyboards and screen readers
              const isDupe = copy !== 1 || i >= products.length;
              return (
                <div key={i} className="box-content w-[335px] shrink-0 pr-[30px]" aria-hidden={isDupe || undefined}>
                  <ProductCard product={product} tabIndex={isDupe ? -1 : undefined} />
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
