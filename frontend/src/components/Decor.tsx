export function Decor() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[520px] overflow-hidden">
      <span className="blossom h-44 w-44 bg-[#e8a8b0]/45" style={{ left: "-2rem", top: "4rem" }} />
      <span className="blossom h-24 w-24 bg-[#c9a84c]/30" style={{ left: "16%", top: "1.2rem" }} />
      <span className="blossom h-10 w-10 bg-[#e8a8b0]/70" style={{ left: "28%", top: "5.5rem" }} />
      <span className="blossom h-56 w-56 bg-[#d7e4f2]" style={{ right: "-3rem", top: "-1rem" }} />
      <span className="blossom h-16 w-16 bg-[#5b8fb5]/25" style={{ right: "22%", top: "6rem" }} />
    </div>
  );
}
