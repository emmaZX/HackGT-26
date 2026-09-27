import Link from "next/link";
import { ProductCard as Product } from "@/lib/types";
import { headline, kicker, meta } from "@/lib/headline";
import { ProductImage } from "./ProductImage";

/** "recent updates" card, style A: image, kicker, headline, meta */
export function ProductCard({ product, tabIndex }: { product: Product; tabIndex?: number }) {
  const k = kicker(product);
  const info = meta(product);

  return (
    <Link
      href={`/product/${product.slug}`}
      tabIndex={tabIndex}
      draggable={false}
      className="card flex h-[370px] flex-col overflow-hidden transition-shadow hover:shadow-[0_8px_22px_rgba(3,29,78,0.14)]"
    >
      <ProductImage product={product} recall={k.isRecall} className="h-[178px] shrink-0" />

      <div className="flex min-h-0 flex-1 flex-col px-[20px] pb-[16px] pt-[15px]">
        <p className="font-raleway text-[12px] font-semibold tracking-[-0.02em] text-[#627290]">
          {k.status && <span className={k.isRecall ? "text-[#d9546a]" : "text-[#031d4e]"}>{k.status}</span>}
          {k.status && " · "}
          {k.source}
        </p>
        <h3 className="line-clamp-3 mt-[6px] font-mulish text-[21px] font-semibold leading-[1.15] tracking-[-0.04em] text-[#031d4e]">
          {headline(product)}
        </h3>
        {info && <p className="mt-auto pt-2 font-mulish text-[12px] tracking-[-0.02em] text-[#627290]">{info}</p>}
      </div>
    </Link>
  );
}