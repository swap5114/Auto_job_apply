"use client";

import { motion } from "framer-motion";
import { easeOutExpo } from "@/lib/motion";

type Direction = "up" | "down" | "left" | "right" | "none";

const OFFSET: Record<Direction, { x?: number; y?: number }> = {
  up: { y: 24 },
  down: { y: -24 },
  left: { x: 24 },
  right: { x: -24 },
  none: {},
};

/**
 * Reveal — a small scroll-triggered entrance wrapper used across the landing
 * page. Fades + slides its children in the first time they enter the viewport.
 * Keeps the animation language identical everywhere so the page feels cohesive.
 */
export function Reveal({
  children,
  direction = "up",
  delay = 0,
  duration = 0.6,
  amount = 0.3,
  className,
}: {
  children: React.ReactNode;
  direction?: Direction;
  delay?: number;
  duration?: number;
  amount?: number;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, ...OFFSET[direction] }}
      whileInView={{ opacity: 1, x: 0, y: 0 }}
      viewport={{ once: true, amount }}
      transition={{ duration, delay, ease: easeOutExpo }}
    >
      {children}
    </motion.div>
  );
}
