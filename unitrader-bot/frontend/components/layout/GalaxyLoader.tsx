/**
 * GalaxyLoader — brand loading animation.
 *
 * Spins the galaxy logo image (public/logo-galaxy.png) using a plain CSS
 * animation. Drop the PNG/SVG into public/ and it works immediately.
 *
 * Usage:
 *   <GalaxyLoader />                          — 72 px, no label
 *   <GalaxyLoader size={48} />                — custom size
 *   <GalaxyLoader label="Loading…" />         — text beneath
 *   <GalaxyLoader fullScreen />               — centred in the viewport
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
  const spinner = (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/logo-galaxy.png"
      alt="Loading"
      width={size}
      height={size}
      className="uw-galaxy-spin"
      style={{ width: size, height: size }}
    />
  );

  if (fullScreen) {
    return (
      <div className="flex h-screen w-full flex-col items-center justify-center gap-4 bg-dark-950">
        {spinner}
        {label && (
          <p className="text-xs text-dark-400 animate-pulse">{label}</p>
        )}
      </div>
    );
  }

  if (label) {
    return (
      <div className="flex flex-col items-center gap-3">
        {spinner}
        <p className="text-xs text-dark-400 animate-pulse">{label}</p>
      </div>
    );
  }

  return spinner;
}
