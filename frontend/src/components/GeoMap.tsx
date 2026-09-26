"use client";

import { useEffect, useRef } from "react";
import type { Map as LeafletMap, LayerGroup } from "leaflet";
import "leaflet/dist/leaflet.css";
import { Signal } from "@/lib/types";
import { CITIES } from "@/lib/identity";

const DEFAULT = CITIES[0]; // Atlanta

/**
 * CARTO started requiring an API key in Aug 2026 (keyless tiles get an "API KEY REQUIRED" watermark).
 * With NEXT_PUBLIC_CARTO_API_KEY set we use CARTO Positron; otherwise Esri's keyless light-grey canvas.
 */
const CARTO_KEY = process.env.NEXT_PUBLIC_CARTO_API_KEY || "";

function tileLayer(L: typeof import("leaflet")) {
  if (CARTO_KEY) {
    return L.tileLayer(
      `https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png?key=${encodeURIComponent(CARTO_KEY)}`,
      {
        maxZoom: 18,
        subdomains: "abcd",
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
      },
    );
  }
  return L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 16, attribution: "Tiles &copy; Esri" },
  );
}

/**
 * Light grey street map, no labels, to match the Figma frame.
 * Pink circles mark cities with reports; size grows with the count.
 */
export function GeoMap({
  geography,
  city,
  className = "h-[465px]",
}: {
  geography: Signal["geography"];
  city?: string | null;
  className?: string;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<LeafletMap | null>(null);
  const layer = useRef<LayerGroup | null>(null);
  const places = geography
    .map((g) => ({ ...g, city: CITIES.find((c) => c.label === g.label) }))
    .filter((g) => g.city);
  const key = JSON.stringify(places.map((p) => [p.label, p.count])) + (city || "");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const L = (await import("leaflet")).default;
      if (cancelled || !el.current) return;

      if (!map.current) {
        map.current = L.map(el.current, {
          zoomControl: false,
          scrollWheelZoom: true, // wheel and trackpad pinch zoom the map, not the page
          attributionControl: true,
          zoomSnap: 0.5, // smoother trackpad pinch
        });
        tileLayer(L).addTo(map.current);
        layer.current = L.layerGroup().addTo(map.current);
      }

      layer.current!.clearLayers();
      for (const p of places) {
        L.circleMarker([p.city!.lat, p.city!.lng], {
          radius: Math.min(22, 7 + p.count * 2),
          color: "#ff96a6",
          weight: 2,
          fillColor: "#ff96a6",
          fillOpacity: 0.45,
        })
          .bindTooltip(`${p.label} · ${p.count} ${p.count === 1 ? "report" : "reports"}`)
          .addTo(layer.current!);
      }

      const home = CITIES.find((c) => c.label === city) || DEFAULT;
      if (places.length > 1) {
        map.current.fitBounds(
          L.latLngBounds(places.map((p) => [p.city!.lat, p.city!.lng] as [number, number])),
          { padding: [60, 60], maxZoom: 11 },
        );
      } else if (places.length === 1) {
        map.current.setView([places[0].city!.lat, places[0].city!.lng], 11);
      } else {
        map.current.setView([home.lat, home.lng], 11);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => () => {
    map.current?.remove();
    map.current = null;
  }, []);

  return (
    <div className={`relative isolate overflow-hidden rounded-[16px] bg-[#e5e5e5] ${className}`}>
      <div ref={el} className="absolute inset-0" />
      <div className="absolute bottom-[22px] right-[22px] z-[500] grid gap-[7px]">
        <ZoomButton label="Zoom in" onClick={() => map.current?.zoomIn()} d="M12 6v12M6 12h12" />
        <ZoomButton label="Zoom out" onClick={() => map.current?.zoomOut()} d="M6 12h12" />
      </div>
      {!places.length && (
        <div className="absolute left-4 top-4 z-[500] rounded-full bg-white/90 px-3 py-1 text-xs text-[#627290] shadow-sm">
          No reports with a city here yet
        </div>
      )}
    </div>
  );
}

function ZoomButton({ label, onClick, d }: { label: string; onClick: () => void; d: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="grid h-[34px] w-[34px] place-items-center rounded-full bg-white shadow-[0_2px_6px_rgba(3,29,78,0.12)] hover:bg-[#f8f8ff]"
    >
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="#c0d4ef" strokeWidth="1.6" strokeLinecap="round">
        <path d={d} />
      </svg>
    </button>
  );
}