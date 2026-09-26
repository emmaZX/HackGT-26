"use client";

import { useEffect, useState } from "react";
import { CITIES, getCity, locationPromptSeen, markLocationPromptSeen, nearestCity, setCity } from "@/lib/identity";

export function LocationPrompt({ onChange }: { onChange: (city: string | null) => void }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    onChange(getCity());
    if (!locationPromptSeen()) setOpen(true);
  }, [onChange]);

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
    <div className="card mx-auto mb-8 max-w-6xl p-5">
      <div className="serif text-xl">Want to see what’s happening near you?</div>
      <p className="mt-2 text-sm text-[#5a6d80]">
        We only keep a city name, never a street address. You can skip this and still use the site.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button onClick={allow} className="btn-primary px-4 py-2 text-sm">
          Use my approximate city
        </button>
        {CITIES.slice(0, 3).map((city) => (
          <button key={city.label} onClick={() => choose(city.label)} className="btn-soft px-4 py-2 text-sm">
            I&apos;m in {city.label}
          </button>
        ))}
        <button onClick={() => choose(null)} className="px-4 py-2 text-sm text-[#5a6d80]">
          Not now
        </button>
      </div>
    </div>
  );
}
