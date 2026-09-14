import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";

/**
 * Panel — the single canonical elevated surface for the app.
 *
 * This replaces the two competing card styles that had drifted apart:
 *   - the local `Panel` copies in dashboard/matches (rounded-2xl + shadow-card)
 *   - the shared `<Card>` (rounded-xl + shadow-elevation-low)
 *
 * Everything that presents content on the canvas should use this so surfaces
 * feel identical on every screen.
 *
 * Props:
 *   - `interactive` — adds a hover elevation (for clickable list/grid items).
 *   - `asChild` — render the styling onto a child element (e.g. a motion.div)
 *     instead of an extra wrapper, so entrance animations stay intact.
 */
const Panel = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & {
    interactive?: boolean;
    asChild?: boolean;
  }
>(({ className, interactive = false, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "div";
  return (
    <Comp
      ref={ref}
      className={cn(
        "rounded-2xl border border-border/70 bg-card shadow-card",
        interactive && "transition-shadow duration-300 hover:shadow-card-hover",
        className
      )}
      {...props}
    />
  );
});
Panel.displayName = "Panel";

export { Panel };
