import { fullName } from "@/lib/headline";

/**
 * image_lookup.py stores the photo credit in the URL fragment: "...jpg#credit=Photo%3A...".
 * Official CPSC photos have no credit and show untagged.
 */
function splitCredit(url: string): { src: string; credit: string | null } {
  const [src, fragment] = url.split("#credit=");
  if (!fragment) return { src: url, credit: null };
  try {
    return { src, credit: decodeURIComponent(fragment) };
  } catch {
    return { src, credit: null };
  }
}

/**
 * Product image: the photo when there is one. Credited free photos are cropped to fill the area;
 * official CPSC photos are shown whole on white. Otherwise a flat tinted block with the product name set large.
 */
export function ProductImage({
  product,
  recall = false,
  className = "",
}: {
  product: { image_url?: string | null; name: string; brand?: string | null };
  recall?: boolean;
  className?: string;
}) {
  if (product.image_url) {
    const { src, credit } = splitCredit(product.image_url);
    return (
      <div className={`relative flex items-center justify-center bg-white ${className}`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={product.name}
          draggable={false}
          loading="lazy"
          // Credited photos fill the whole area; official CPSC photos (product on white) stay whole
          className={credit ? "h-full w-full object-cover" : "h-full w-full object-contain p-3"}
        />
        {credit && (
          <span className="absolute bottom-2 left-2 right-2 truncate rounded-full bg-white/90 px-2 py-[2px] text-[10px] text-[#627290] shadow-sm">
            {credit}
          </span>
        )}
      </div>
    );
  }
  return (
    <div className={`flex items-end p-[18px] ${recall ? "bg-[#ffe3e8]" : "bg-[#ecf0fc]"} ${className}`}>
      <span
        className={`line-clamp-2 font-mulish text-[30px] font-bold leading-[1.05] tracking-[-0.06em] ${
          recall ? "text-[#ffb3bf]" : "text-[#c0d4ef]"
        }`}
      >
        {fullName(product)}
      </span>
    </div>
  );
}