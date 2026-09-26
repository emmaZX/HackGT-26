"use client";

import { ReactNode, useEffect, useRef, useState } from "react";

type TypeaheadProps<T> = {
  label: string;
  placeholder: string;
  query: string;
  onQuery: (value: string) => void;
  items: T[];
  itemKey: (item: T) => string;
  renderItem: (item: T) => ReactNode;
  onSelect: (item: T) => void;
  selected?: ReactNode;
  onClearSelected?: () => void;
  footer?: ReactNode;
  loading?: boolean;
  hint?: string;
};

export function Typeahead<T>({
  label,
  placeholder,
  query,
  onQuery,
  items,
  itemKey,
  renderItem,
  onSelect,
  selected,
  onClearSelected,
  footer,
  loading,
  hint,
}: TypeaheadProps<T>) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function close(event: MouseEvent) {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  if (selected) {
    return (
      <label className="grid gap-1 text-sm">
        {label}
        <div className="field flex items-center justify-between gap-3">
          <div className="min-w-0">{selected}</div>
          {onClearSelected && (
            <button type="button" onClick={onClearSelected} className="shrink-0 text-sm text-[#627290]">
              Change
            </button>
          )}
        </div>
      </label>
    );
  }

  const showList = open && (loading || items.length > 0 || Boolean(footer) || query.trim().length >= 2);

  return (
    <label className="grid gap-1 text-sm">
      {label}
      <div ref={box} className="relative">
        <input
          value={query}
          onChange={(e) => {
            onQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder={placeholder}
          className="field w-full"
          autoComplete="off"
        />
        {hint && <p className="mt-1 text-xs text-[#627290]">{hint}</p>}
        {showList && (
          <div className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-2xl border border-[#e0e3e9] bg-white shadow-lg">
            {loading && <div className="px-4 py-3 text-sm text-[#627290]">Looking…</div>}
            {items.map((item) => (
              <button
                key={itemKey(item)}
                type="button"
                onClick={() => {
                  onSelect(item);
                  setOpen(false);
                }}
                className="block w-full px-4 py-2.5 text-left text-sm hover:bg-[#f8f8ff]"
              >
                {renderItem(item)}
              </button>
            ))}
            <div onClick={() => setOpen(false)}>{footer}</div>
          </div>
        )}
      </div>
    </label>
  );
}
