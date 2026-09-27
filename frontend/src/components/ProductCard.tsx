import Link from "next/link";
import { ProductCard as Product } from "@/lib/types";
import { headline, kicker, meta } from "@/lib/headline";
import { ProductImage } from "./ProductImage";

/** "recent updates" card — keep teammate photos; show linked source hosts when present */
export function ProductCard({ product, tabIndex }: { product: Product; tabIndex?: number }) {
  const k = kicker(product);
  const info = meta(product);
  const links = (product.evidence || []).filter((e) => e.source_url).slice(0, 3);

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
        {links.length > 0 && (
          <p className="mt-1 line-clamp-1 font-mulish text-[11px] tracking-[-0.02em] text-[#8a94a8]">
            {links.map((e, i) => {
              let host = e.source || "source";
              try {
                host = new URL(e.source_url).hostname.replace(/^www\./, "");
              } catch {
                /* keep */
              }
              return (
                <span key={e.source_url}>
                  {i > 0 ? " · " : ""}
                  <span
                    role="link"
                    tabIndex={-1}
                    onClick={(ev) => {
                      ev.preventDefault();
                      ev.stopPropagation();
                      window.open(e.source_url, "_blank", "noopener,noreferrer");
                    }}
                    className="underline decoration-[#c0d4ef] underline-offset-2 hover:text-[#031d4e]"
                  >
                    {host}
                  </span>
                </span>
              );
            })}
          </p>
        )}
      </div>
    </Link>
  );
}
