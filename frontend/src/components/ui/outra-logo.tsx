"use client";

import React from "react";
import { motion } from "framer-motion";

/**
 * Outra brand mark + wordmark.
 *
 * Design notes
 * ------------
 * The mark is a single geometric "O" built as an open aperture ring: a near
 * three-quarter arc whose gap opens toward the upper right, with a small
 * "signal" node sitting in that opening. It reads as an open outbound channel
 * — outreach leaving the loop — while still resolving as an O for "Outra".
 *
 * It's drawn on a 32x32 grid with a single consistent stroke, so it stays
 * crisp from a 16px favicon up to a hero lockup. Colour comes from the
 * landing page's signature coral -> peach accent gradient
 * (--accent-1 / --accent-2), with a `mono` option for single-colour contexts
 * (print, embossing, dark UI chrome).
 *
 * The `animated` variant draws the arc on, fires the signal node, and then
 * the "Outra" wordmark emerges *out of the mark*: it starts collapsed against
 * the symbol (clipped + shifted left + slightly scaled down) and unfurls to
 * the right, letter by letter, as if being emitted from the aperture. It
 * respects prefers-reduced-motion via framer-motion's reduced-motion handling.
 */

type LogoSize = "sm" | "md" | "lg" | "xl";

interface OutraLogoProps {
  className?: string;
  size?: LogoSize;
  /** Render only the mark, without the "Outra" wordmark. */
  markOnly?: boolean;
  /** Animate the mark on mount (arc draw-on + signal pulse). */
  animated?: boolean;
  /** Use a single flat colour (currentColor) instead of the accent gradient. */
  mono?: boolean;
}

const SIZES: Record<
  LogoSize,
  { mark: number; text: string; gap: string }
> = {
  sm: { mark: 22, text: "text-lg", gap: "gap-1.5" },
  md: { mark: 28, text: "text-xl", gap: "gap-2" },
  lg: { mark: 36, text: "text-2xl", gap: "gap-2.5" },
  xl: { mark: 56, text: "text-4xl", gap: "gap-3" },
};

// Unique gradient id per instance so multiple logos on a page don't collide.
let _idCounter = 0;

export function OutraLogo({
  size = "md",
  className = "",
  markOnly = false,
  animated = false,
  mono = false,
}: OutraLogoProps) {
  const dims = SIZES[size];
  const gradientId = React.useMemo(() => `outra-grad-${_idCounter++}`, []);
  const stroke = mono ? "currentColor" : `url(#${gradientId})`;

  // Open aperture: an arc that sweeps ~300deg, leaving a gap at the top-right
  // where the signal node lives. Centre (16,16), radius 10.
  // Start just past the gap (top-right), sweep clockwise all the way around.
  const R = 10;
  const cx = 16;
  const cy = 16;
  // Gap centred at -35deg (upper right). Arc runs from +10deg around to -80deg.
  const startAngle = 12; // degrees
  const endAngle = 360 - 58; // sweep ~290deg, stopping before the gap
  const toXY = (deg: number) => {
    const r = (deg * Math.PI) / 180;
    return [cx + R * Math.cos(r), cy - R * Math.sin(r)] as const;
  };
  const [sx, sy] = toXY(startAngle);
  const [ex, ey] = toXY(endAngle);
  // largeArc = 1 because sweep > 180deg; sweepFlag 1 = clockwise in SVG's
  // y-down space (we negated y above so this traces the ring the long way).
  const arcPath = `M ${sx.toFixed(2)} ${sy.toFixed(2)} A ${R} ${R} 0 1 0 ${ex.toFixed(
    2
  )} ${ey.toFixed(2)}`;

  // Signal node sits in the aperture gap (upper-right), just outside the ring.
  const [nx, ny] = toXY(-23);
  const nodeX = cx + (nx - cx) * 1.02;
  const nodeY = cy + (ny - cy) * 1.02;

  const MarkTag: any = animated ? motion.svg : "svg";
  const PathTag: any = animated ? motion.path : "path";
  const NodeTag: any = animated ? motion.circle : "circle";

  // Timing (seconds): arc draws -> node fires -> word emerges from the mark.
  const ARC_DUR = 0.75;
  const NODE_AT = ARC_DUR - 0.05;
  const WORD_AT = ARC_DUR + 0.1;

  // The wordmark container wipes open from the left (against the mark) and
  // slides out to the right, so the text reads as spilling out of the symbol.
  const wordContainer = {
    hidden: {},
    visible: {
      transition: { delayChildren: WORD_AT, staggerChildren: 0.045 },
    },
  };

  // Each letter starts tucked left (toward the mark), squished and faded, then
  // pops out to its resting spot with a tiny overshoot.
  const letterVariants = {
    hidden: { opacity: 0, x: -10, scaleX: 0.4 },
    visible: {
      opacity: 1,
      x: 0,
      scaleX: 1,
      transition: { type: "spring", stiffness: 520, damping: 30, mass: 0.6 },
    },
  };

  const LETTERS = "Outra".split("");

  return (
    <div className={`inline-flex items-center ${dims.gap} ${className}`}>
      <MarkTag
        width={dims.mark}
        height={dims.mark}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-label="Outra"
        role="img"
        {...(animated
          ? {
            initial: "hidden",
            animate: "visible",
          }
          : {})}
      >
        {!mono && (
          <defs>
            <linearGradient
              id={gradientId}
              x1="4"
              y1="4"
              x2="28"
              y2="28"
              gradientUnits="userSpaceOnUse"
            >
              {/* accent-1 (coral) -> accent-2 (peach) from globals.css */}
              <stop offset="0%" stopColor="hsl(14 82% 63%)" />
              <stop offset="100%" stopColor="hsl(28 88% 68%)" />
            </linearGradient>
          </defs>
        )}

        {/* Open aperture arc */}
        <PathTag
          d={arcPath}
          stroke={stroke}
          strokeWidth={2.5}
          strokeLinecap="round"
          {...(animated
            ? {
              variants: {
                hidden: { pathLength: 0, opacity: 0 },
                visible: {
                  pathLength: 1,
                  opacity: 1,
                  transition: {
                    pathLength: { duration: ARC_DUR, ease: "easeInOut" },
                    opacity: { duration: 0.2 },
                  },
                },
              },
            }
            : {})}
        />

        {/* Signal node in the aperture */}
        <NodeTag
          cx={nodeX}
          cy={nodeY}
          r={2.4}
          fill={stroke}
          {...(animated
            ? {
              variants: {
                hidden: { scale: 0, opacity: 0 },
                visible: {
                  scale: [0, 1.4, 1],
                  opacity: 1,
                  transition: { delay: NODE_AT, duration: 0.45, ease: "easeOut" },
                },
              },
              style: { transformOrigin: `${nodeX}px ${nodeY}px` },
            }
            : {})}
        />
      </MarkTag>

      {!markOnly &&
        (animated ? (
          <motion.span
            className={`font-display ${dims.text} inline-flex overflow-hidden font-semibold tracking-tight text-foreground`}
            variants={wordContainer}
            initial="hidden"
            animate="visible"
            aria-label="Outra"
          >
            {LETTERS.map((ch, i) => (
              <motion.span
                key={i}
                className="inline-block origin-left"
                variants={letterVariants}
                aria-hidden
              >
                {ch}
              </motion.span>
            ))}
          </motion.span>
        ) : (
          <span
            className={`font-display ${dims.text} font-semibold tracking-tight text-foreground`}
          >
            Outra
          </span>
        ))}
    </div>
  );
}
