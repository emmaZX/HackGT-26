export type Location = {
  label: string | null;
  latitude: number | null;
  longitude: number | null;
  precision: string;
};

export type Signal = {
  signal_type: string;
  severity_key: string;
  severity_label: string;
  report_count: number;
  independent_count: number;
  recent_report_count: number;
  previous_report_count: number;
  velocity_percent: number | null;
  source_diversity: number;
  unique_source_ids: number;
  geographic_count: number;
  geography: { label: string; count: number }[];
  issues: { slug: string; name: string; icon: string; count: number }[];
  explanation: string;
  official_recall: {
    agency: string;
    recall_date: string;
    reason: string;
    hazard: string;
    source_url: string;
    nationwide: boolean;
    status?: string;
    phase?: "ongoing" | "past" | string;
  } | null;
  components: Record<string, number>;
};

export type ProductCard = {
  id: number;
  slug: string;
  brand: string;
  name: string;
  model: string | null;
  category: string;
  upc: string | null;
  manufacturer: string | null;
  summary: string | null;
  signal: Signal;
  local: boolean;
  tags: string[];
};

export type ReportCard = {
  id: number;
  source: string;
  source_url: string | null;
  title: string | null;
  text: string;
  excerpt: string;
  created_at: string | null;
  location: Location;
  is_user_generated: boolean;
  is_duplicate: boolean;
  independence_weight: number;
  display_name: string | null;
  issues: { slug: string; name: string; icon: string }[];
  product_slug?: string;
  product_name?: string;
};

export type PostCard = {
  id: number;
  product_id: number;
  display_name: string;
  title: string | null;
  body: string;
  location_label: string | null;
  created_at: string | null;
  like_count: number;
  liked_by: string[];
  liked_by_subs: string[];
  comments: {
    id: number;
    display_name: string;
    body: string;
    created_at: string | null;
  }[];
};

export type ProductDetail = ProductCard & {
  official_status: {
    state: string;
    headline: string;
    detail: string;
    recall: Signal["official_recall"];
  };
  reports: ReportCard[];
  posts: PostCard[];
  disclaimer: string;
  timeline: {
    day_offset: number;
    label: string;
    event_type: string;
    report_count: number;
    detail: string | null;
  }[];
  filtered_issue: string | null;
};

export type Feed = {
  important: ProductCard[];
  nearby: ProductCard[];
  trending: ProductCard[];
  recent_reports: ReportCard[];
  visitor_city: string | null;
  disclaimer: string;
};
