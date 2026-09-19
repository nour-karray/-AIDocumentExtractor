"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "success";
  size?: "sm" | "md" | "lg" | "icon";
};

export function Button({
  className,
  variant = "primary",
  size = "md",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl border text-sm font-semibold transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-55",
        size === "sm" && "h-9 px-3.5 text-[13px]",
        size === "md" && "h-10 px-4",
        size === "lg" && "h-11 px-5",
        size === "icon" && "h-10 w-10",
        variant === "primary" &&
          "border-[#7f56ff] bg-gradient-to-r from-[#7c4dff] to-[#6d43f0] text-white shadow-[0_10px_22px_rgba(120,85,255,0.22)] hover:brightness-105",
        variant === "secondary" &&
          "border-[rgba(145,152,178,0.24)] bg-white text-[#1b2440] hover:border-[rgba(124,77,255,0.26)] hover:bg-[#f7f5ff] dark:border-white/10 dark:bg-[#121829] dark:text-white dark:hover:bg-[#161d31]",
        variant === "ghost" &&
          "border-transparent bg-transparent text-[#6e7797] hover:border-[rgba(145,152,178,0.18)] hover:bg-white dark:text-[#9ca6c6] dark:hover:bg-white/5",
        variant === "danger" &&
          "border-[#f3c1c8] bg-white text-[#df4d64] hover:bg-[#fff5f6] dark:border-[#6b2030] dark:bg-[#29151a] dark:text-[#ff93a5]",
        variant === "success" &&
          "border-[#37c978] bg-[#30c56f] text-white shadow-[0_10px_22px_rgba(48,197,111,0.18)] hover:brightness-105",
        className
      )}
      {...props}
    />
  );
}
