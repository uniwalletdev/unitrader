"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";

interface Props {
  confidence: number; // 0–100
  aiName: string;
  marketCondition?: string | null;
  compact?: boolean; // horizontal bar variant for small spaces
}

function getZone(c: number) {
  if (c >= 70) return { label: "Confident", color: "#0adb6a", bg: "rgba(10,219,106,0.15)", glow: "rgba(10,219,106,0.4)" };
  if (c >= 40) return { label: "Watching", color: "#facc15", bg: "rgba(250,204,21,0.15)", glow: "rgba(250,204,21,0.3)" };
  return { label: "Cautious", color: "#f87171", bg: "rgba(248,113,113,0.15)", glow: "rgba(248,113,113,0.3)" };
}

function CompactBar({ confidence, aiName }: { confidence: number; aiName: string }) {
  const zone = getZone(confidence);
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 w-24 rounded-full bg-dark-800 overflow-hidden">
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ background: zone.color }}
          initial={{ width: 0 }}
          animate={{ width: `${confidence}%` }}
          transition={{ duration: 0.8, ease: "easeOut" }}
        />
      </div>
      <span className="text-xs tabular-nums" style={{ color: zone.color }}>
        {confidence}%
      </span>
    </div>
  );
}

export default function AIConfidenceGauge({ confidence, aiName, marketCondition, compact }: Props) {
  if (compact) return <CompactBar confidence={confidence} aiName={aiName} />;

  const zone = useMemo(() => getZone(confidence), [confidence]);
  const clamped = Math.max(0, Math.min(100, confidence));

  // SVG arc: 180° semi-circle, radius 80, stroke-dasharray trick
  const R = 80;
  const CIRCUMFERENCE = Math.PI * R; // half-circle
  const offset = CIRCUMFERENCE * (1 - clamped / 100);

  // Needle angle: 0% = -180° (left), 100% = 0° (right)
  const needleAngle = -180 + (clamped / 100) * 180;

  return (
    <div className="flex flex-col items-center select-none">
      <div className="relative" style={{ width: 200, height: 115 }}>
        {/* Glow when high confidence */}
        {clamped >= 80 && (
          <motion.div
            className="absolute inset-0 rounded-full blur-2xl"
            style={{ background: zone.glow, top: -10 }}
            animate={{ opacity: [0.3, 0.6, 0.3] }}
            transition={{ duration: 2, repeat: Infinity }}
          />
        )}

        <svg viewBox="0 0 200 110" className="w-full h-full">
          {/* Background track */}
          <path
            d="M 10 100 A 80 80 0 0 1 190 100"
            fill="none"
            stroke="#1a1f2e"
            strokeWidth={14}
            strokeLinecap="round"
          />

          {/* Colored arc */}
          <motion.path
            d="M 10 100 A 80 80 0 0 1 190 100"
            fill="none"
            stroke={zone.color}
            strokeWidth={14}
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            initial={{ strokeDashoffset: CIRCUMFERENCE }}
            animate={{ strokeDashoffset: offset }}
            transition={{ duration: 1.2, ease: "easeOut" }}
          />

          {/* Needle */}
          <motion.line
            x1={100}
            y1={100}
            x2={100}
            y2={30}
            stroke={zone.color}
            strokeWidth={2.5}
            strokeLinecap="round"
            style={{ transformOrigin: "100px 100px" }}
            initial={{ rotate: -180 }}
            animate={{ rotate: needleAngle }}
            transition={{ duration: 1.2, ease: "easeOut" }}
          />

          {/* Center dot */}
          <circle cx={100} cy={100} r={4} fill={zone.color} />
        </svg>

        {/* Center value */}
        <div className="absolute inset-x-0 bottom-0 text-center">
          <motion.span
            className="text-2xl font-bold tabular-nums"
            style={{ color: zone.color }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.4 }}
          >
            {clamped}%
          </motion.span>
        </div>
      </div>

      {/* Label */}
      <p className="mt-1 text-sm text-dark-300">
        <span className="font-medium" style={{ color: zone.color }}>
          {aiName}
        </span>{" "}
        is{" "}
        <span style={{ color: zone.color }}>{zone.label}</span>
      </p>

      {marketCondition && (
        <span
          className="mt-1 inline-block rounded-full px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-wider"
          style={{ background: zone.bg, color: zone.color }}
        >
          {marketCondition}
        </span>
      )}
    </div>
  );
}
