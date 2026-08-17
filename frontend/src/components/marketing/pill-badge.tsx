import { cn } from "@/lib/utils";

export function PillBadge({
  children,
  className,
  icon,
}: {
  children: React.ReactNode;
  className?: string;
  icon?: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground shadow-[0px_1px_2px_0px_rgba(0,0,0,0.04)]",
        className
      )}
    >
      {icon}
      {children}
    </span>
  );
}
