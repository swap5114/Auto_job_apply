"use client";

import { motion } from "framer-motion";
import { useId } from "react";

export type DonutSegment = { label: string; value: number; color: string };

export function DonutChart({
  segments,
  size = 148,
  stroke = 16,
  center,
}: {
  segments: DonutSegment[];
  size?: number;
  stroke?: number;
  center?: React.ReactNode;
}) {
  const gradId = useId();
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const total = segments.reduce((s, seg) => s + seg.value, 0) || 1;

  let cumulative = 0;

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="hsl(var(--accent-1))" />
            <stop offset="100%" stopColor="hsl(var(--accent-2))" />
          </linearGradient>
        </defs>
        {/* Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="hsl(var(--muted))"
          strokeWidth={stroke}
        />
        {segments.map((seg, i) => {
          const fraction = seg.value / total;
          const dash = fraction * circumference;
          const startAngle = (cumulative / total) * 360;
          cumulative += seg.value;
          const strokeColor = seg.color === "accent" ? `url(#${gradId})` : seg.color;
          return (
            <motion.circle
              key={i}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={strokeColor}
              strokeWidth={stroke}
              strokeLinecap="round"
              transform={`rotate(${startAngle} ${size / 2} ${size / 2})`}
              strokeDasharray={`${dash} ${circumference}`}
              initial={{ strokeDasharray: `0 ${circumference}` }}
              whileInView={{ strokeDasharray: `${dash} ${circumference}` }}
              viewport={{ once: true }}
              transition={{ duration: 1, delay: 0.2 + i * 0.15, ease: [0.21, 1.02, 0.73, 1] }}
            />
          );
        })}
      </svg>
      {center && (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          {center}
        </div>
      )}
    </div>
  );
}
