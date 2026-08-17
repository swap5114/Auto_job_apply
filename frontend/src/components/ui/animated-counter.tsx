"use client";

import { useEffect, useRef } from "react";
import { animate, useInView } from "framer-motion";
import { easeOutExpo } from "@/lib/motion";

export function AnimatedCounter({
  value,
  duration = 1.1,
  className,
  suffix = "",
  decimals = 0,
}: {
  value: number;
  duration?: number;
  className?: string;
  suffix?: string;
  decimals?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });

  useEffect(() => {
    if (!inView || !ref.current) return;
    const controls = animate(0, value, {
      duration,
      ease: easeOutExpo,
      onUpdate(v) {
        if (ref.current) {
          ref.current.textContent =
            (decimals > 0 ? v.toFixed(decimals) : Math.round(v).toString()) +
            suffix;
        }
      },
    });
    return () => controls.stop();
  }, [inView, value, duration, suffix, decimals]);

  return (
    <span ref={ref} className={className}>
      0{suffix}
    </span>
  );
}
