"use client";

import { useEffect, useState } from "react";
import { CITIES, getCity, locationPromptSeen, markLocationPromptSeen, nearestCity, setCity } from "@/lib/identity";

export function LocationPrompt({ onChange }: { onChange: (city: string | null) => void }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    // Parent owns the initial city read — only open the prompt when needed.
    if (!locationPromptSeen()) setOpen(true);
  }, []);

  function choose(city: string | null) {
    setCity(city);
    markLocationPromptSeen();
    onChange(city);
    setOpen(false);
  }

  function allow() {
    if (!navigator.geolocation) {
      choose("Atlanta");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => choose(nearestCity(pos.coords.latitude, pos.coords.longitude).label),
      () => choose(null),
      { enableHighAccuracy: false, timeout: 6000 },
    );
  }

  if (!open) return null;

  return (
    <div className="card mb-8 flex flex-wrap items-center gap-x-6 gap-y-3 px-5 py-4">
      <div className="min-w-0 flex-1">
        <div className="font-raleway text-[18px] font-medium tracking-[-0.04em]">See what&apos;s happening near you?</div>
        <p className="mt-1 text-sm text-[#627290]">We only keep a city name, never an address. Skipping is fine.</p>
      </div>
      <div className="flex flex-wrap gap-2 text-sm">
        <button onClick={allow} className="btn-primary px-4 py-2">Use my city</button>
        {CITIES.slice(0, 3).map((city) => (
          <button key={city.label} onClick={() => choose(city.label)} className="btn-soft px-4 py-2">
            {city.label}
          </button>
        ))}
        <button onClick={() => choose(null)} className="px-3 py-2 text-[#627290]">Not now</button>
      </div>
    </div>
  );
}
