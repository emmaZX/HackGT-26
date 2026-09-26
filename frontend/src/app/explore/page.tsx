"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ProductCard as Product } from "@/lib/types";
import { ProductCard } from "@/components/ProductCard";

export default function ExplorePage() {
  const [products, setProducts] = useState<Product[]>([]);

  useEffect(() => {
    api.products().then((data) => setProducts(data.products));
  }, []);

  return (
    <div>
      <h1 className="serif text-4xl">Browse products</h1>
      <p className="mt-2 max-w-2xl text-[#627290]">
        Each page keeps the official recall, if there is one, separate from neighbor stories.
      </p>
      <div className="mt-8 grid gap-[30px] sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {products.map((product) => (
          <ProductCard key={product.slug} product={product} />
        ))}
      </div>
    </div>
  );
}
