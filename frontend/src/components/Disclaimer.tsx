export function Disclaimer({ text }: { text?: string }) {
  return (
    <p className="text-sm leading-relaxed text-[#5a6d80]">
      {text ||
        "A cluster of neighbor reports is a heads-up, not proof that a product is unsafe. A missing official recall does not mean a product is safe."}
    </p>
  );
}
