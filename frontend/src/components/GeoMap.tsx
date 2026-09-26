import { Signal } from "@/lib/types";
import { CITIES } from "@/lib/identity";

export function GeoMap({ geography }: { geography: Signal["geography"] }) {
  if (!geography.length) {
    return (
      <div className="card p-5 text-sm text-[#5a6d80]">
        These notes do not include a city. That is okay — they still count in the overall picture.
      </div>
    );
  }

  return (
    <div className="card overflow-hidden p-5">
      <div className="relative h-56 overflow-hidden rounded-2xl bg-[#d7e4f2]">
        <div
          className="absolute inset-0 opacity-50"
          style={{
            backgroundImage:
              "linear-gradient(rgba(26,54,93,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(26,54,93,0.08) 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
        />
        {geography.map((item) => {
          const city = CITIES.find((c) => c.label === item.label);
          if (!city) return null;
          const left = ((city.lng + 125) / 55) * 100;
          const top = ((50 - city.lat) / 22) * 100;
          return (
            <div
              key={item.label}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${Math.min(90, Math.max(8, left))}%`, top: `${Math.min(88, Math.max(12, top))}%` }}
            >
              <div className="h-3.5 w-3.5 rounded-full bg-[#e8a8b0] shadow-[0_0_0_8px_rgba(232,168,176,0.28)]" />
              <div className="mt-1 whitespace-nowrap text-[11px] text-[#1a365d]">
                {item.label} · {item.count}
              </div>
            </div>
          );
        })}
      </div>
      <ul className="mt-4 grid gap-2 text-sm md:grid-cols-2">
        {geography.map((item) => (
          <li key={item.label} className="flex justify-between text-[#5a6d80]">
            <span>📍 {item.label}</span>
            <span>{item.count} {item.count === 1 ? "note" : "notes"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
