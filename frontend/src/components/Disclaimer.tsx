export function Disclaimer({ text }: { text?: string }) {
  return (
    <p className="max-w-3xl text-xs leading-relaxed text-[#627290]">
      {text ||
        "A cluster of neighbor reports is a heads-up, not proof that a product is unsafe. A missing official recall does not mean a product is safe."}
    </p>
  );
}
