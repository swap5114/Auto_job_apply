"use client";

import { useEffect, useId, useRef, useState } from "react";
import { motion } from "framer-motion";

export type AreaPoint = { label: string; sent: number; replied: number };

export function AreaChart({
  data,
  height = 260,
}: {
  data: AreaPoint[];
  height?: number;
}) {
  const gradId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(760);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) setW(width);
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const padL = 34;
  const padR = 14;
  const padT = 18;
  const padB = 28;
  const plotW = Math.max(1, w - padL - padR);
  const plotH = height - padT - padB;

  const rawMax = Math.max(...data.map((d) => Math.max(d.sent, d.replied)), 1);
  const niceMax = Math.max(4, Math.ceil(rawMax / 4) * 4);
  const stepX = data.length > 1 ? plotW / (data.length - 1) : 0;

  const x = (i: number) => padL + i * stepX;
  const y = (v: number) => padT + plotH - (v / niceMax) * plotH;

  const sentLine = data
    .map((d, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d.sent).toFixed(1)}`)
    .join(" ");
  const sentArea = `${sentLine} L ${x(data.length - 1).toFixed(1)} ${(padT + plotH).toFixed(1)} L ${x(0).toFixed(1)} ${(padT + plotH).toFixed(1)} Z`;
  const repliedLine = data
    .map((d, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d.replied).toFixed(1)}`)
    .join(" ");

  const gridVals = [0, niceMax / 4, niceMax / 2, (niceMax * 3) / 4, niceMax];
  const labelEvery = Math.ceil(data.length / 7);

  function handleMove(e: React.MouseEvent<HTMLDivElement>) {
    if (!ref.current || stepX === 0) return;
    const rect = ref.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    let idx = Math.round((mx - padL) / stepX);
    idx = Math.max(0, Math.min(data.length - 1, idx));
    setHover(idx);
  }

  const tipLeft = hover != null ? Math.min(Math.max(x(hover), 64), w - 64) : 0;

  return (
    <div
      ref={ref}
      className="relative w-full select-none"
      onMouseMove={handleMove}
      onMouseLeave={() => setHover(null)}
      style={{ height }}
    >
      <svg width={w} height={height} className="block">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="hsl(var(--accent-1))" stopOpacity="0.22" />
            <stop offset="100%" stopColor="hsl(var(--accent-1))" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Gridlines + y labels */}
        {gridVals.map((v, i) => (
          <g key={i}>
            <line
              x1={padL}
              x2={w - padR}
              y1={y(v)}
              y2={y(v)}
              stroke="hsl(var(--border))"
              strokeWidth={1}
              strokeDasharray={i === 0 ? "0" : "3 4"}
              opacity={i === 0 ? 1 : 0.6}
            />
            <text
              x={padL - 8}
              y={y(v) + 3}
              textAnchor="end"
              className="fill-muted-foreground"
              fontSize={10}
            >
              {Math.round(v)}
            </text>
          </g>
        ))}

        {/* Area fill */}
        <motion.path
          d={sentArea}
          fill={`url(#${gradId})`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.4 }}
        />

        {/* Sent line */}
        <motion.path
          d={sentLine}
          fill="none"
          stroke="hsl(var(--accent-1))"
          strokeWidth={2.25}
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1.1, ease: [0.21, 1.02, 0.73, 1] }}
        />

        {/* Replied line (dashed, muted) */}
        <motion.path
          d={repliedLine}
          fill="none"
          stroke="hsl(var(--muted-foreground))"
          strokeWidth={1.5}
          strokeDasharray="4 4"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1.1, delay: 0.2, ease: [0.21, 1.02, 0.73, 1] }}
        />

        {/* X labels */}
        {data.map((d, i) =>
          i % labelEvery === 0 || i === data.length - 1 ? (
            <text
              key={i}
              x={x(i)}
              y={height - 8}
              textAnchor="middle"
              className="fill-muted-foreground"
              fontSize={10}
            >
              {d.label}
            </text>
          ) : null
        )}

        {/* Hover crosshair + dots */}
        {hover != null && (
          <g>
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={padT}
              y2={padT + plotH}
              stroke="hsl(var(--foreground))"
              strokeWidth={1}
              strokeDasharray="3 3"
              opacity={0.25}
            />
            <circle cx={x(hover)} cy={y(data[hover].replied)} r={3.5} fill="hsl(var(--muted-foreground))" />
            <circle
              cx={x(hover)}
              cy={y(data[hover].sent)}
              r={5}
              fill="hsl(var(--background))"
              stroke="hsl(var(--accent-1))"
              strokeWidth={2.5}
            />
          </g>
        )}
      </svg>

      {/* Tooltip */}
      {hover != null && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-lg border bg-card px-3 py-2 shadow-dropdown"
          style={{ left: tipLeft, top: 4 }}
        >
          <p className="mb-1 text-[11px] font-medium text-muted-foreground">
            {data[hover].label}
          </p>
          <div className="flex items-center gap-3 text-xs">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-accent1" />
              <span className="font-semibold tabular-nums text-foreground">
                {data[hover].sent}
              </span>
              <span className="text-muted-foreground">sent</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-muted-foreground" />
              <span className="font-semibold tabular-nums text-foreground">
                {data[hover].replied}
              </span>
              <span className="text-muted-foreground">replied</span>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
