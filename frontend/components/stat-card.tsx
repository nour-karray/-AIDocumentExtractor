import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";

type StatCardProps = {
  icon: ReactNode;
  title: string;
  value: string;
  helper: string;
  accentClass?: string;
  sparkColor?: string;
};

export function StatCard({
  icon,
  title,
  value,
  helper,
  accentClass = "text-[#1b2440] dark:text-white",
  sparkColor = "#7c4dff"
}: StatCardProps) {
  return (
    <Card className="min-h-[126px] p-4">
      <div className="flex h-full flex-col justify-between gap-4">
        <div className="flex items-start justify-between gap-3">
          <div className="text-[12px] font-semibold text-[#7a83a2] dark:text-[#98a2c3]">
            {title}
          </div>
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#f4f2ff] text-[#7c4dff] dark:bg-[#20193b]">
            {icon}
          </div>
        </div>
        <div>
          <div className={`proto-title text-[30px] font-bold ${accentClass}`}>{value}</div>
          <p className="mt-1 text-[12px] leading-5 text-[#7a83a2] dark:text-[#98a2c3]">{helper}</p>
          <div className="mt-3 h-9 rounded-xl bg-[#fafbff] px-1 py-1 dark:bg-white/5">
            <svg viewBox="0 0 100 30" className="h-full w-full">
              <polyline
                fill="none"
                stroke={sparkColor}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                points="0,24 15,22 30,23 45,18 60,16 75,12 90,14 100,8"
              />
            </svg>
          </div>
        </div>
      </div>
    </Card>
  );
}
