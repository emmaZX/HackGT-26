const API = process.env.NEXT_PUBLIC_API_URL || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
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
  like: (postId: number, display_name: string) =>
    request<{ post: import("./types").PostCard }>(`/api/posts/${postId}/likes`, {
      method: "POST",
      body: JSON.stringify({ display_name }),
    }),
  discover: (slug: string, extra?: string) =>
    request<{ provider: string | null; message?: string; ingested: number; queries?: string[] }>(
      `/api/products/${slug}/discover`,
      { method: "POST", body: JSON.stringify({ extra }) },
    ),
};

export type SearchResult = {
  query: string;
  products: import("./types").ProductCard[];
  reports: import("./types").ReportCard[];
  semantic: { product: import("./types").ProductCard; score: number; matched_excerpt: string }[];
};
