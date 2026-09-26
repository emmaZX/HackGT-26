const NAME_KEY = "signal.displayName";
const CITY_KEY = "signal.city";
const LOC_PROMPT_KEY = "signal.locationPrompt";

export const CITIES = [
  { label: "Atlanta", lat: 33.75, lng: -84.39 },
  { label: "Marietta", lat: 33.95, lng: -84.55 },
  { label: "Decatur", lat: 33.77, lng: -84.3 },
  { label: "Boston", lat: 42.36, lng: -71.06 },
  { label: "Chicago", lat: 41.88, lng: -87.63 },
  { label: "Austin", lat: 30.27, lng: -97.74 },
  { label: "Seattle", lat: 47.61, lng: -122.33 },
];

export function getDisplayName() {
  if (typeof window === "undefined") return "Neighbor";
  return localStorage.getItem(NAME_KEY) || "Neighbor";
}

export function setDisplayName(name: string) {
  localStorage.setItem(NAME_KEY, name.slice(0, 80));
}

export function getCity() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(CITY_KEY);
}

export function setCity(city: string | null) {
  if (!city) localStorage.removeItem(CITY_KEY);
  else localStorage.setItem(CITY_KEY, city);
}

export function locationPromptSeen() {
  return typeof window !== "undefined" && localStorage.getItem(LOC_PROMPT_KEY) === "1";
}

export function markLocationPromptSeen() {
  localStorage.setItem(LOC_PROMPT_KEY, "1");
}

export function nearestCity(lat: number, lng: number) {
  return CITIES.reduce((best, city) => {
    const d = (city.lat - lat) ** 2 + (city.lng - lng) ** 2;
    return d < best.d ? { city, d } : best;
  }, { city: CITIES[0], d: Infinity }).city;
}

export function timeAgo(iso: string | null) {
  if (!iso) return "";
  const then = new Date(iso.endsWith("Z") ? iso : `${iso}Z`).getTime();
  const delta = Date.now() - then;
  const hours = Math.round(delta / 36e5);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}
