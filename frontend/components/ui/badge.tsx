import type { PropsWithChildren } from "react";

import { cn } from "@/lib/utils";

type BadgeProps = PropsWithChildren<{
  className?: string;
  tone?: "default" | "success" | "warning" | "danger" | "purple";
}>;

export function Badge({ children, className, tone = "default" }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold",
        tone === "default" &&
          "border-[rgba(140,148,170,0.2)] bg-[#f8faff] text-[#6c7598] dark:border-white/10 dark:bg-white/5 dark:text-[#aab4d1]",
        tone === "success" &&
          "border-[#bee8ce] bg-[#effcf4] text-[#24a256] dark:border-[#1f6b41] dark:bg-[#0f2b1e] dark:text-[#7df7af]",
        tone === "warning" &&
          "border-[#f1e1a6] bg-[#fffaf0] text-[#b88607] dark:border-[#6c5815] dark:bg-[#30260e] dark:text-[#ffd576]",
        tone === "danger" &&
          "border-[#f3c1c8] bg-[#fff4f6] text-[#df4d64] dark:border-[#6b2030] dark:bg-[#29151a] dark:text-[#ff9aac]",
        tone === "purple" &&
          "border-[#d7ccff] bg-[#f5f0ff] text-[#7455f2] dark:border-[#47328c] dark:bg-[#1d1736] dark:text-[#c7b7ff]",
        className
      )}
    >
      {children}
    </span>
  );
}
