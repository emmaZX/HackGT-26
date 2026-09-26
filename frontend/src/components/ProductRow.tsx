import Link from "next/link";
import { ProductCard as Product } from "@/lib/types";
import { StatusBadge, isRecallTag, splitTags } from "./Tag";

/** "products you may use" row from the home frame (537 × 86 in Figma) */
export function ProductRow({ product }: { product: Product }) {
  const { status } = splitTags(product.tags);
  const blurb = product.summary || product.signal.explanation;

  return (
    <Link
      href={`/product/${product.slug}`}
      className="card block min-h-[86px] px-[19px] pb-3 pt-[13px] transition-shadow hover:shadow-[0_8px_22px_rgba(3,29,78,0.14)]"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="border-b border-[#e0e3e9] pb-[3px] pr-3 font-mulish text-[14px] font-normal leading-tight tracking-[-0.04em] text-[#031d4e]">
          {product.name}
        </h3>
        {status && isRecallTag(status) && (
          <div className="-mr-[6px] -mt-[3px] shrink-0">
            <StatusBadge label={status} />
          </div>
        )}
      </div>
      <p className="line-clamp-2 mt-[9px] font-mulish text-[10px] font-light leading-[13px] tracking-[-0.04em] text-[#627290]">
        {blurb}
      </p>
    </Link>
  );
}
