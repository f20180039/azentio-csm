/** Illustration for the sign-in page: a live voice call turning into a verified answer and a ticket. Inline SVG, no network. */
export function SignInArt() {
  const bars = [10, 22, 34, 18, 40, 28, 14, 36, 24, 12, 30, 20, 8];
  return (
    <svg className="signin-art-svg" viewBox="0 0 420 300" role="img" aria-label="A customer call being answered by the voice agent">
      <defs>
        <linearGradient id="si-glow" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#4ff0b0" stopOpacity="0.35" />
          <stop offset="1" stopColor="#4ff0b0" stopOpacity="0" />
        </linearGradient>
      </defs>
      <circle cx="96" cy="118" r="86" fill="url(#si-glow)" />
      {/* headset */}
      <g transform="translate(46 70)" fill="none" stroke="#e8f1f8" strokeWidth="6" strokeLinecap="round">
        <path d="M14 58 V44 a36 36 0 0 1 72 0 V58" />
        <rect x="4" y="52" width="18" height="34" rx="8" fill="#29c483" stroke="none" />
        <rect x="78" y="52" width="18" height="34" rx="8" fill="#29c483" stroke="none" />
        <path d="M87 86 q0 22 -26 24 h-10" />
        <circle cx="47" cy="110" r="5" fill="#4ff0b0" stroke="none" />
      </g>
      {/* live waveform */}
      <g transform="translate(36 214)">
        {bars.map((h, i) => (
          <rect key={i} className="si-bar" style={{ animationDelay: `${i * 0.09}s` }} x={i * 11} y={-h / 2} width="6" height={h} rx="3" fill="#4ff0b0" />
        ))}
      </g>
      {/* customer bubble */}
      <g transform="translate(200 40)">
        <rect width="196" height="52" rx="14" fill="#163a63" />
        <text x="16" y="22" fontFamily="Source Sans 3, system-ui, sans-serif" fontSize="12" fill="#a9bfd3">Customer</text>
        <text x="16" y="40" fontFamily="Source Sans 3, system-ui, sans-serif" fontSize="14" fill="#e8f1f8">When is my next EMI?</text>
      </g>
      {/* agent bubble */}
      <g transform="translate(176 108)">
        <rect width="220" height="70" rx="14" fill="#29c483" />
        <text x="16" y="22" fontFamily="Source Sans 3, system-ui, sans-serif" fontSize="12" fill="#0d6b40">Agent · verified</text>
        <text x="16" y="42" fontFamily="Source Sans 3, system-ui, sans-serif" fontSize="14" fill="#0d2340">₹12,450 due on 5 November.</text>
        <text x="16" y="59" fontFamily="Source Sans 3, system-ui, sans-serif" fontSize="12" fill="#0d2340">Retrieved from the loan system</text>
      </g>
      {/* verified + ticket chips */}
      <g transform="translate(200 198)">
        <rect width="92" height="30" rx="15" fill="#dcf6ea" />
        <path d="M14 15 l5 5 l9 -10" fill="none" stroke="#0d6b40" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <text x="34" y="20" fontFamily="Source Sans 3, system-ui, sans-serif" fontSize="12" fontWeight="700" fill="#0d6b40">Verified</text>
        <rect x="102" width="94" height="30" rx="8" fill="#fff2d9" />
        <text x="114" y="20" fontFamily="JetBrains Mono, ui-monospace, monospace" fontSize="12" fontWeight="600" fill="#7a4a00">SR-40200</text>
      </g>
    </svg>
  );
}
