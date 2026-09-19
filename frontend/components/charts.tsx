import type { ChartDatum, DailyDatum, TrendSeries } from "@/lib/types";

export function SimpleBars({ data }: { data: ChartDatum[] }) {
  const max = Math.max(...data.map((item) => item.value), 1);
  return (
    <div className="space-y-3">
      {data.map((item) => (
        <div key={item.label} className="grid grid-cols-[1fr,120px,26px] items-center gap-3">
          <div className="truncate text-[12px] text-[#4b5575] dark:text-[#b1bcda]">{item.label}</div>
          <div className="h-2 rounded-full bg-[#eef1fa] dark:bg-white/8">
            <div
              className="h-2 rounded-full bg-gradient-to-r from-[#7c4dff] to-[#64d79d]"
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
          <div className="text-right text-[12px] font-semibold text-[#1b2440] dark:text-white">
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}

export function DonutChart({ data }: { data: ChartDatum[] }) {
  const total = data.reduce((sum, item) => sum + item.value, 0) || 1;
  let cursor = 0;
  const colors = ["#7c4dff", "#30c56f", "#4d8bff", "#ffb540", "#f05d7b"];
  const segments = data.map((item, index) => {
    const start = cursor;
    const size = (item.value / total) * 100;
    cursor += size;
    return `${colors[index % colors.length]} ${start}% ${cursor}%`;
  });

  return (
    <div className="flex flex-col items-center gap-5 lg:flex-row lg:items-center">
      <div
        className="relative flex h-44 w-44 items-center justify-center rounded-full"
        style={{ background: `conic-gradient(${segments.join(", ")})` }}
      >
        <div className="flex h-28 w-28 flex-col items-center justify-center rounded-full bg-white shadow-[0_8px_24px_rgba(19,29,61,0.08)] dark:bg-[#101625] dark:shadow-none">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[#8b93ac]">
            Total
          </div>
          <div className="proto-title mt-1 text-[30px] font-bold text-[#1b2440] dark:text-white">
            {total}
          </div>
        </div>
      </div>
      <div className="w-full space-y-2.5">
        {data.map((item, index) => (
          <div key={item.label} className="flex items-center justify-between gap-3 text-sm">
            <div className="flex items-center gap-3">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: colors[index % colors.length] }}
              />
              <span className="text-[#626d8c] dark:text-[#b1bcda]">{item.label}</span>
            </div>
            <span className="font-semibold text-[#1b2440] dark:text-white">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function TrendLineChart({ series }: { series: TrendSeries[] }) {
  const allPoints = series.flatMap((item) => item.points);
  if (!allPoints.length) {
    return <div className="text-sm text-[#8b93ac]">Aucune donnee disponible.</div>;
  }

  const labels = series[0]?.points.map((point) => point.date) ?? [];
  const max = Math.max(...allPoints.map((point) => point.value), 1);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4 text-[11px]">
        {series.map((item) => (
          <div key={item.label} className="flex items-center gap-2 text-[#6f7898] dark:text-[#b1bcda]">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
            {item.label}
          </div>
        ))}
      </div>
      <svg viewBox="0 0 100 34" className="h-48 w-full overflow-visible">
        {[0, 8, 16, 24, 32].map((line) => (
          <line
            key={line}
            x1="0"
            x2="100"
            y1={line}
            y2={line}
            stroke="rgba(151,159,184,0.18)"
            strokeDasharray="2 3"
          />
        ))}
        {series.map((item) => {
          const points = item.points
            .map((point, index) => {
              const x = (index / Math.max(item.points.length - 1, 1)) * 100;
              const y = 32 - (point.value / max) * 28;
              return `${x},${y}`;
            })
            .join(" ");
          return (
            <polyline
              key={item.label}
              fill="none"
              stroke={item.color}
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              points={points}
            />
          );
        })}
      </svg>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#8b93ac]">
        {labels.map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
    </div>
  );
}

export function SparklineChart({ data }: { data: DailyDatum[] }) {
  if (!data.length) {
    return <div className="text-sm text-[#8b93ac]">Aucune donnee disponible.</div>;
  }

  const max = Math.max(...data.map((item) => item.documents), 1);
  const points = data
    .map((item, index) => {
      const x = (index / Math.max(data.length - 1, 1)) * 100;
      const y = 100 - (item.documents / max) * 100;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="space-y-4">
      <svg viewBox="0 0 100 100" className="h-40 w-full overflow-visible">
        <defs>
          <linearGradient id="sparklineGradient" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="#30c56f" />
            <stop offset="100%" stopColor="#7c4dff" />
          </linearGradient>
        </defs>
        <polyline
          fill="none"
          points={points}
          stroke="url(#sparklineGradient)"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="3"
        />
      </svg>
      <div className="flex flex-wrap items-center justify-between gap-3 text-[11px] text-[#8b93ac]">
        {data.map((item) => (
          <span key={`${item.date}-${item.documents}`}>{item.date}</span>
        ))}
      </div>
    </div>
  );
}

export function ComboChart({
  data,
  successRate
}: {
  data: DailyDatum[];
  successRate: number;
}) {
  if (!data.length) {
    return <div className="text-sm text-[#8b93ac]">Aucune donnee disponible.</div>;
  }

  const max = Math.max(...data.map((item) => item.documents), 1);
  const linePoints = data
    .map((item, index) => {
      const x = 10 + index * (80 / Math.max(data.length - 1, 1));
      const value = Math.max(20, Math.min(90, successRate));
      const y = 90 - value * 0.6;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4 text-[11px] text-[#6f7898] dark:text-[#b1bcda]">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-[#7c4dff]" />
          Succes
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-[#ef5f5f]" />
          Erreurs
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-[#30c56f]" />
          Taux de succes
        </div>
      </div>
      <svg viewBox="0 0 100 100" className="h-44 w-full">
        {[20, 40, 60, 80].map((line) => (
          <line
            key={line}
            x1="8"
            x2="96"
            y1={100 - line}
            y2={100 - line}
            stroke="rgba(151,159,184,0.18)"
            strokeDasharray="2 3"
          />
        ))}
        {data.map((item, index) => {
          const x = 12 + index * (80 / Math.max(data.length - 1, 1));
          const height = (item.documents / max) * 56;
          const errorHeight = height * 0.18;
          return (
            <g key={item.date}>
              <rect x={x - 2.8} y={88 - height} width="5" height={height} rx="1.6" fill="#7c4dff" opacity="0.82" />
              <rect x={x + 3} y={88 - errorHeight} width="5" height={errorHeight} rx="1.6" fill="#ef5f5f" opacity="0.82" />
            </g>
          );
        })}
        <polyline
          fill="none"
          stroke="#30c56f"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={linePoints}
        />
      </svg>
      <div className="flex flex-wrap items-center justify-between gap-3 text-[11px] text-[#8b93ac]">
        {data.map((item) => (
          <span key={item.date}>{item.date}</span>
        ))}
      </div>
    </div>
  );
}
