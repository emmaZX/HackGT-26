import Link from "next/link";
import { ProductCard as Product } from "@/lib/types";
import { Tag } from "./Tag";

export function ProductCard({ product }: { product: Product }) {
  const signal = product.signal;
  const tone = signal.official_recall
    ? "border-[#e8a8b0]"
    : signal.severity_key.includes("emerging")
      ? "border-[#e6d09a]"
      : "border-[#e4d9c8]";

  return (
    <Link href={`/product/${product.slug}`} className={`card rise block p-5 ${tone} transition hover:-translate-y-0.5 hover:shadow-lg`}>
      <div className="mb-3 flex flex-wrap gap-2">
        {product.tags.map((tag) => (
          <Tag key={tag} label={tag} />
        ))}
      </div>
      <div className="text-xs uppercase tracking-[0.14em] text-[#5b8fb5]">{product.brand}</div>
      <h3 className="serif mt-1 text-2xl leading-tight">{product.name}</h3>
      <p className="mt-3 text-sm leading-relaxed text-[#5a6d80]">{signal.explanation}</p>
      <div className="mt-4 flex flex-wrap gap-4 text-xs text-[#5a6d80]">
        <span>{signal.report_count} reports</span>
        <span>about {signal.independent_count} different people</span>
        {signal.velocity_percent != null && signal.velocity_percent > 0 && (
          <span className="text-[#c45c6a]">+{signal.velocity_percent}% this week</span>
        )}
      </div>
    </Link>
  );
}
