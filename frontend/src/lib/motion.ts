import type { Variants, Transition } from "framer-motion";

// Cal.com-style easing (cubic-bezier tuple)
export const easeOutExpo: [number, number, number, number] = [
  0.21, 1.02, 0.73, 1,
];
export const easeSpring: Transition = {
  type: "spring",
  stiffness: 400,
  damping: 34,
};

// Container that staggers its children
export const staggerContainer = (stagger = 0.06, delayChildren = 0): Variants => ({
  hidden: {},
  show: {
    transition: { staggerChildren: stagger, delayChildren },
  },
});

// Fade + rise — the workhorse entrance
export const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: easeOutExpo },
  },
};

// Subtle scale-in for cards / stats
export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  show: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.45, ease: easeOutExpo },
  },
};

// Slide in from left (list rows)
export const slideInLeft: Variants = {
  hidden: { opacity: 0, x: -10 },
  show: { opacity: 1, x: 0, transition: { duration: 0.4, ease: easeOutExpo } },
};

// Hover lift for interactive cards
export const hoverLift = {
  rest: { y: 0 },
  hover: { y: -3, transition: easeSpring },
};
