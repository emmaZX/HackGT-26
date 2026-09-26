"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, LocationHit } from "@/lib/api";
import { useAuth } from "@/lib/AuthProvider";
import { getCity, setCity } from "@/lib/identity";
import { Typeahead } from "@/components/Typeahead";
import { ProductCard as Product } from "@/lib/types";

export default function ReportPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-2xl text-[#627290]">One moment…</div>}>
      <ReportForm />
    </Suspense>
  );
}

function ReportForm() {
  const router = useRouter();
  const params = useSearchParams();
  const hintedProduct = params.get("product") || "";
  const { ready, user } = useAuth();
  const [products, setProducts] = useState<Product[]>([]);
  const [productQuery, setProductQuery] = useState("");
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [addingNew, setAddingNew] = useState(false);
  const [cityQuery, setCityQuery] = useState("");
  const [cityResults, setCityResults] = useState<LocationHit[]>([]);
  const [selectedCity, setSelectedCity] = useState<LocationHit | null>(null);
  const [cityLoading, setCityLoading] = useState(false);
  const [payload, setPayload] = useState({
    product_name: "",
    brand: "",
    model: "",
    upc: "",
    text: "",
  });
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.products().then((data) => setProducts(data.products));
    const saved = getCity();
    if (saved) {
      setSelectedCity({ label: saved, latitude: null, longitude: null, detail: "" });
    }
    if (hintedProduct) {
      setProductQuery(hintedProduct);
      setAddingNew(true);
      setPayload((current) => ({ ...current, product_name: current.product_name || hintedProduct }));
    }
  }, [hintedProduct]);

  useEffect(() => {
    if (ready && !user) {
      router.replace("/login?next=/report");
    }
  }, [ready, user, router]);

  useEffect(() => {
    const q = cityQuery.trim();
    if (selectedCity || q.length < 2) {
      setCityResults([]);
      return;
    }
    const handle = window.setTimeout(async () => {
      setCityLoading(true);
      try {
        const data = await api.locations(q);
        setCityResults(data.locations);
      } catch {
        setCityResults([]);
      } finally {
        setCityLoading(false);
      }
    }, 250);
    return () => window.clearTimeout(handle);
  }, [cityQuery, selectedCity]);

  const productMatches = useMemo(() => {
    const q = productQuery.trim().toLowerCase();
    if (!q) return products.slice(0, 8);
    return products
      .filter((product) =>
        [product.name, product.brand, product.model, product.upc]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(q)),
      )
      .slice(0, 8);
  }, [productQuery, products]);

  const exactProduct = productMatches.some(
    (product) => product.name.toLowerCase() === productQuery.trim().toLowerCase(),
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selectedProduct && !addingNew) {
      setMessage("Search for a product, or add a new one.");
      return;
    }
    if (addingNew && !payload.product_name.trim()) {
      setMessage("Please name the new product.");
      return;
    }
    setBusy(true);
    try {
      if (selectedCity) setCity(selectedCity.label);
      const result = await api.report({
        product_slug: selectedProduct?.slug || "",
        product_name: addingNew ? payload.product_name : "",
        brand: addingNew ? payload.brand : "",
        model: addingNew ? payload.model : "",
        upc: addingNew ? payload.upc : "",
        text: payload.text,
        location_label: selectedCity?.label || null,
        latitude: selectedCity?.latitude ?? null,
        longitude: selectedCity?.longitude ?? null,
      });
      setMessage(result.message);
      router.push(`/product/${result.product.slug}`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not submit");
    } finally {
      setBusy(false);
    }
  }

  if (!ready || !user) {
    return <div className="mx-auto max-w-2xl text-[#627290]">One moment…</div>;
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="serif text-4xl">Tell us what happened</h1>
      <p className="mt-2 text-[#627290]">
        Your note always helps the overall picture. Adding a city is optional. Posting as{" "}
        <strong className="text-[#031d4e]">{user.displayName}</strong>.
      </p>
      <form onSubmit={submit} className="card mt-8 grid gap-4 p-6">
        <Typeahead
          label="Which product?"
          placeholder="Search a product, brand, or model"
          query={productQuery}
          onQuery={(value) => {
            setProductQuery(value);
            setAddingNew(false);
          }}
          items={productMatches}
          itemKey={(product) => product.slug}
          renderItem={(product) => (
            <span>
              <span className="font-medium text-[#031d4e]">{product.name}</span>
              <span className="text-[#627290]"> · {product.brand}</span>
            </span>
          )}
          onSelect={(product) => {
            setSelectedProduct(product);
            setAddingNew(false);
            setProductQuery(product.name);
          }}
          selected={
            selectedProduct ? (
              <span>
                <strong>{selectedProduct.name}</strong>
                <span className="text-[#627290]"> · {selectedProduct.brand}</span>
              </span>
            ) : addingNew ? (
              <span>
                New product: <strong>{payload.product_name || productQuery || "untitled"}</strong>
              </span>
            ) : null
          }
          onClearSelected={() => {
            setSelectedProduct(null);
            setAddingNew(false);
            setProductQuery("");
          }}
          hint="Pick a match, or add it if it is not in the list yet."
          footer={
            productQuery.trim() && !exactProduct ? (
              <button
                type="button"
                onClick={() => {
                  setAddingNew(true);
                  setSelectedProduct(null);
                  setPayload((current) => ({
                    ...current,
                    product_name: current.product_name || productQuery.trim(),
                  }));
                }}
                className="block w-full border-t border-[#e0e3e9] px-4 py-2.5 text-left text-sm text-[#031d4e] hover:bg-[#f8f8ff]"
              >
                Add a new product: <strong>{productQuery.trim()}</strong>
              </button>
            ) : null
          }
        />
        {addingNew && (
          <div className="grid gap-3 md:grid-cols-2">
            <input
              placeholder="Product name"
              required
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
        <Typeahead
          label="City, if you want to share it"
          placeholder="Look up a city"
          query={cityQuery}
          onQuery={(value) => {
            setCityQuery(value);
            setSelectedCity(null);
          }}
          items={cityResults}
          itemKey={(city) => `${city.label}-${city.latitude}-${city.longitude}`}
          renderItem={(city) => (
            <span>
              <span className="font-medium text-[#031d4e]">{city.label}</span>
              {city.detail && <span className="text-[#627290]"> · {city.detail}</span>}
            </span>
          )}
          onSelect={(city) => {
            setSelectedCity(city);
            setCityQuery(city.label);
          }}
          selected={selectedCity ? <strong>{selectedCity.label}</strong> : null}
          onClearSelected={() => {
            setSelectedCity(null);
            setCityQuery("");
            setCity(null);
          }}
          loading={cityLoading}
          hint="Optional. Search any city — you can skip this."
        />
        <button disabled={busy} className="btn-primary px-5 py-3 disabled:opacity-40">
          {busy ? "Sending…" : "Share my note"}
        </button>
        {message && <p className="text-sm text-[#627290]">{message}</p>}
      </form>
      <p className="mt-4 text-sm text-[#627290]">
        Not you?{" "}
        <Link href="/login?next=/report" className="font-semibold text-[#031d4e]">
          Switch accounts
        </Link>
      </p>
    </div>
  );
}
