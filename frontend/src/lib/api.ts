import { getIdToken } from "./auth";

const API = process.env.NEXT_PUBLIC_API_URL || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  };
  const method = (init?.method || "GET").toUpperCase();
  if (method !== "GET") {
    const token = await getIdToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || "Request failed");
  }
  return response.json();
}

export const api = {
  feed: (city?: string | null) =>
    request<import("./types").Feed>(`/api/feed${city ? `?city=${encodeURIComponent(city)}` : ""}`),
  products: () => request<{ products: import("./types").ProductCard[] }>("/api/products"),
  product: (slug: string, issue?: string | null) =>
    request<import("./types").ProductDetail>(
      `/api/products/${slug}${issue ? `?issue=${encodeURIComponent(issue)}` : ""}`,
    ),
  search: (q: string) => request<SearchResult>(`/api/search?q=${encodeURIComponent(q)}`),
  locations: (q: string) =>
    request<{ locations: LocationHit[] }>(`/api/locations?q=${encodeURIComponent(q)}`),
  report: (payload: Record<string, unknown>) =>
    request<{ message: string; product: import("./types").ProductDetail }>("/api/reports", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  post: (payload: Record<string, unknown>) =>
    request<{ post: import("./types").PostCard }>("/api/posts", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  comment: (postId: number, payload: Record<string, unknown>) =>
    request<{ post: import("./types").PostCard }>(`/api/posts/${postId}/comments`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  like: (postId: number) =>
    request<{ post: import("./types").PostCard }>(`/api/posts/${postId}/likes`, {
      method: "POST",
    }),
  discover: (slug: string, extra?: string) =>
    request<{
      provider: string | null;
      message?: string;
      ingested: number;
      queries?: string[];
      agent_log?: { agent: string; [key: string]: unknown }[];
    }>(`/api/products/${slug}/discover`, {
      method: "POST",
      body: JSON.stringify({ extra, force: true }),
    }),
};

export type LocationHit = {
  label: string;
  latitude: number | null;
  longitude: number | null;
  detail: string;
};

export type SearchResult = {
  query: string;
  products: import("./types").ProductCard[];
  reports: import("./types").ReportCard[];
  semantic: { product: import("./types").ProductCard; score: number; matched_excerpt: string }[];
  discovery?: {
    provider: string | null;
    ingested: number;
    message?: string | null;
    skipped?: boolean | null;
  } | null;
};
