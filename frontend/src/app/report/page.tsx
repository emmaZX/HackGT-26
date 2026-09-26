"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { CITIES, getCity, getDisplayName, setDisplayName } from "@/lib/identity";
import { ProductCard as Product } from "@/lib/types";

export default function ReportPage() {
  const router = useRouter();
  const [products, setProducts] = useState<Product[]>([]);
  const [displayName, setName] = useState("Neighbor");
  const [payload, setPayload] = useState({
    product_slug: "acme-x100",
    product_name: "",
    brand: "",
    model: "",
    upc: "",
    text: "",
    location_label: "",
  });
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setName(getDisplayName());
    setPayload((current) => ({ ...current, location_label: getCity() || "" }));
    api.products().then((data) => setProducts(data.products));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setDisplayName(displayName);
    try {
      const result = await api.report({
        ...payload,
        display_name: displayName,
        location_label: payload.location_label || null,
      });
      setMessage(result.message);
      router.push(`/product/${result.product.slug}`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not submit");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="serif text-4xl">Tell us what happened</h1>
      <p className="mt-2 text-[#5a6d80]">
        Your note always helps the overall picture. Adding a city is optional.
      </p>
      <form onSubmit={submit} className="card mt-8 grid gap-4 p-6">
        <label className="grid gap-1 text-sm">
          What should we call you?
          <input
            value={displayName}
            onChange={(e) => setName(e.target.value)}
            className="field"
          />
        </label>
        <label className="grid gap-1 text-sm">
          Which product?
          <select
            value={payload.product_slug}
            onChange={(e) => setPayload({ ...payload, product_slug: e.target.value })}
            className="field bg-white"
          >
            {products.map((product) => (
              <option key={product.slug} value={product.slug}>
                {product.name}
              </option>
            ))}
            <option value="">Something else…</option>
          </select>
        </label>
        {!payload.product_slug && (
          <div className="grid gap-3 md:grid-cols-2">
            <input
              placeholder="Product name"
              value={payload.product_name}
              onChange={(e) => setPayload({ ...payload, product_name: e.target.value })}
              className="field"
            />
            <input
              placeholder="Brand"
              value={payload.brand}
              onChange={(e) => setPayload({ ...payload, brand: e.target.value })}
              className="field"
            />
            <input
              placeholder="Model"
              value={payload.model}
              onChange={(e) => setPayload({ ...payload, model: e.target.value })}
              className="field"
            />
            <input
              placeholder="Barcode, if you have it"
              value={payload.upc}
              onChange={(e) => setPayload({ ...payload, upc: e.target.value })}
              className="field"
            />
          </div>
        )}
        <label className="grid gap-1 text-sm">
          What happened?
          <textarea
            required
            minLength={12}
            rows={5}
            value={payload.text}
            onChange={(e) => setPayload({ ...payload, text: e.target.value })}
            placeholder="Started smelling like burning plastic after about 20 minutes."
            className="field"
          />
        </label>
        <label className="grid gap-1 text-sm">
          City, if you want to share it
          <select
            value={payload.location_label}
            onChange={(e) => setPayload({ ...payload, location_label: e.target.value })}
            className="field bg-white"
          >
            <option value="">Skip location</option>
            {CITIES.map((city) => (
              <option key={city.label} value={city.label}>
                {city.label}
              </option>
            ))}
          </select>
        </label>
        <button disabled={busy} className="btn-primary px-5 py-3 disabled:opacity-40">
          {busy ? "Sending…" : "Share my note"}
        </button>
        {message && <p className="text-sm text-[#5a6d80]">{message}</p>}
      </form>
    </div>
  );
}
