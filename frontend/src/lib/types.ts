export type Location = {
  label: string | null;
  latitude: number | null;
  longitude: number | null;
  precision: string;
};

export type SourceTier = "official" | "caers" | "unofficial";

export type SpikeMetrics = {
  recent_count: number;
  baseline_weekly: number;
  velocity_ratio: number;
  window_days: number;
  is_spike?: boolean;
};

export type OutbreakInfo = {
  ref: string;
  pathogen: string;
  cases: string | null;
  active: boolean;
  product_status?: string | null;
  source_url?: string | null;
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
  source_tier?: SourceTier;
  spike?: SpikeMetrics | null;
  outbreak?: OutbreakInfo | null;
  internet_before_official?: boolean;
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
  image_url: string | null;
  signal: Signal;
  local: boolean;
  tags: string[];
  source_tier?: SourceTier;
  evidence_count?: number;
  evidence?: { source_url: string; source: string; observed_at: string | null; excerpt: string }[];
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
  official?: ProductCard[];
  caers_spikes?: ProductCard[];
  unofficial?: ProductCard[];
  nearby: ProductCard[];
  trending: ProductCard[];
  priority_foods?: ProductCard[];
  recent_reports: ReportCard[];
  visitor_city: string | null;
  disclaimer: string;
};
