const STYLES: Record<string, string> = {
  "OFFICIAL RECALL": "bg-[#f8dce0] text-[#9a3140] border border-[#e8a8b0]",
  "EMERGING SIGNAL": "bg-[#f7e8c4] text-[#7a5b16] border border-[#e6d09a]",
  "STRONG SIGNAL": "bg-[#f7e8c4] text-[#7a5b16] border border-[#d4b65a]",
  "ELEVATED REPORTS": "bg-[#ede4d2] text-[#6a5430] border border-[#e4d9c8]",
  "LIMITED REPORTS": "bg-[#eef3f8] text-[#5a6d80] border border-[#d7e4f2]",
  LOCAL: "bg-[#d7e4f2] text-[#1a365d] border border-[#b9cde0]",
  NATIONWIDE: "bg-[#eef3f8] text-[#5a6d80] border border-[#d7e4f2]",
  TRENDING: "bg-[#f6e7ea] text-[#c45c6a] border border-[#e8a8b0]",
  CPSC: "bg-[#eef3f8] text-[#5a6d80] border border-[#d7e4f2]",
  FDA: "bg-[#eef3f8] text-[#5a6d80] border border-[#d7e4f2]",
};

export function Tag({ label }: { label: string }) {
  return <span className={`tag ${STYLES[label] || STYLES["LIMITED REPORTS"]}`}>{label}</span>;
}
