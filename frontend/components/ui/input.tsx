import * as React from "react";

import { cn } from "@/lib/utils";

export function Input({
  className,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-xl border border-[rgba(139,147,172,0.2)] bg-white px-3.5 text-sm text-[#1b2440] outline-none transition placeholder:text-[#99a1bb] focus:border-[#7f56ff] focus:ring-2 focus:ring-[#7f56ff]/10",
        "dark:border-white/10 dark:bg-[#0f1525] dark:text-white dark:placeholder:text-[#7d88aa]",
        className
      )}
      {...props}
    />
  );
}
