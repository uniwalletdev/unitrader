/**
 * GalaxyLoader — brand loading animation.
 *
 * A static galaxy core with a glowing orbit ring that spins around it.
 * The blue-to-orange gradient on the ring and the bright orbit dot
 * mirror the Universal Wallet / Unitrader brand mark.
 *
 * Usage:
 *   <GalaxyLoader />               — default 72px, no label
 *   <GalaxyLoader size={48} />     — smaller
 *   <GalaxyLoader label="Loading your account…" /> — with text beneath
 *   <GalaxyLoader fullScreen />    — centred in the full viewport
 */

interface GalaxyLoaderProps {
  size?: number;
  label?: string;
  fullScreen?: boolean;
}

export default function GalaxyLoader({
  size = 72,
  label,
  fullScreen = false,
}: GalaxyLoaderProps) {
  const half   = size / 2;
  const core   = size * 0.22;   // galaxy core radius
  const haze   = size * 0.30;   // soft spiral-arm haze
  const ring   = size * 0.42;   // orbit ring radius
  const dot    = size * 0.055;  // orbit dot radius
  const stroke = Math.max(1.5, size * 0.025);

  const svg = (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Loading"
      role="img"
    >
      <defs>
        {/* Galaxy core glow */}
        <radialGradient id="uw-core" cx="50%" cy="50%" r="50%">
          <stop offset="0%"   stopColor="#ffe4a0" stopOpacity="1"   />
          <stop offset="40%"  stopColor="#d4813a" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#1a0a30" stopOpacity="0"   />
        </radialGradient>

        {/* Spiral haze */}
        <radialGradient id="uw-haze" cx="50%" cy="50%" r="50%">
          <stop offset="0%"   stopColor="#7040b0" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#1a0a30" stopOpacity="0"    />
        </radialGradient>

        {/* Ring gradient — blue → orange, matching brand */}
        <linearGradient
          id="uw-ring"
          gradientUnits="userSpaceOnUse"
          x1={half - ring}
          y1={half}
          x2={half + ring}
          y2={half}
        >
          <stop offset="0%"   stopColor="#60d0ff" />
          <stop offset="100%" stopColor="#ff8020" />
        </linearGradient>

        {/* Orbit dot glow */}
        <filter id="uw-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation={dot * 1.4} result="blur" />
          <feMerge>
            <feMergeNode in="blur"          />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        {/* Ring glow */}
        <filter id="uw-ring-glow" x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur stdDeviation={stroke * 0.8} result="blur" />
          <feMerge>
            <feMergeNode in="blur"          />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* ── Static galaxy core ─────────────────────────────────────── */}
      <circle cx={half} cy={half} r={haze}  fill="url(#uw-haze)"  />
      <circle cx={half} cy={half} r={core}  fill="url(#uw-core)"  />

      {/* ── Rotating group: ring + orbit dot ───────────────────────── */}
      <g
        style={{
          transformOrigin: `${half}px ${half}px`,
          animation: "uw-orbit 2.4s linear infinite",
        }}
      >
        {/* Ring */}
        <circle
          cx={half}
          cy={half}
          r={ring}
          stroke="url(#uw-ring)"
          strokeWidth={stroke}
          strokeLinecap="round"
          filter="url(#uw-ring-glow)"
          opacity="0.9"
        />

        {/* Orbit dot — sits at top of ring (12 o'clock) */}
        <circle
          cx={half}
          cy={half - ring}
          r={dot}
          fill="#80e8ff"
          filter="url(#uw-glow)"
        />
      </g>
    </svg>
  );

  if (fullScreen) {
    return (
      <div className="flex h-screen w-full flex-col items-center justify-center gap-4 bg-dark-950">
        {svg}
        {label && (
          <p className="text-xs text-dark-400 animate-pulse">{label}</p>
        )}
      </div>
    );
  }

  if (label) {
    return (
      <div className="flex flex-col items-center gap-3">
        {svg}
        <p className="text-xs text-dark-400 animate-pulse">{label}</p>
      </div>
    );
  }

  return svg;
}
