export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span className="relative grid h-10 w-10 place-items-center rounded-full bg-[#d7e4f2] shadow-inner">
        <span className="absolute left-2 top-2 h-3 w-3 rounded-full bg-[#e8a8b0]" />
        <span className="absolute right-2 top-3 h-2.5 w-2.5 rounded-full bg-[#c9a84c]" />
        <span className="absolute bottom-2 left-1/2 h-2 w-2 -translate-x-1/2 rounded-full bg-[#5b8fb5]" />
      </span>
      <div>
        <div className="serif text-[1.35rem] leading-none text-[#1a365d]">Recall Me Maybe</div>
        {!compact && (
          <div className="mt-1 text-[11px] tracking-[0.14em] text-[#5b8fb5]">
            A friendly look at product safety
          </div>
        )}
      </div>
    </div>
  );
}
