/** Figma logo mark (rmm-logo.svg), inlined so it scales with the name */
export function LogoMark({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 54 54" fill="none" aria-hidden className={className}>
      <path d="M54 27C54 41.9117 41.9117 54 27 54C12.0883 54 0 41.9117 0 27C0 12.0883 12.0883 0 27 0C41.9117 0 54 12.0883 54 27Z" fill="#C0D4EF" />
      <path
        d="M28.1074 19.1699C34.4146 18.0662 40.4734 21.0435 48.6641 26.5039C50.0426 27.423 50.4151 29.2855 49.4961 30.6641C48.577 32.0426 46.7145 32.4152 45.3359 31.4961C37.0269 25.9568 32.8353 24.434 29.1426 25.0801C27.2547 25.4105 25.2052 26.3598 22.5732 28.2168C21.4569 29.0045 20.2734 29.931 18.9844 31H25.5312C27.1881 31 28.5312 32.3431 28.5312 34C28.5312 35.6569 27.1881 37 25.5312 37H8V19C8 17.3431 9.34315 16 11 16C12.6569 16 14 17.3431 14 19V27.3506C15.8217 25.7987 17.5111 24.4456 19.1143 23.3145C22.1072 21.2028 24.9955 19.7146 28.1074 19.1699Z"
        fill="white"
      />
    </svg>
  );
}

/**
 * Mark + "recall me maybe" (Mulish Bold, -8%).
 * Everything is in em, so the parent's font-size scales the whole lockup.
 */
export function Logo() {
  return (
    <span className="flex items-start">
      <LogoMark className="h-[1.29em] w-[1.29em] shrink-0" />
      <span className="ml-[0.3em] mt-[0.4em] whitespace-nowrap font-mulish font-bold leading-none tracking-[-0.08em] text-[#031d4e]">
        recall me maybe
      </span>
    </span>
  );
}
