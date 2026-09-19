"use client";

type SwitchProps = {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
};

export function Switch({ checked, onChange, label }: SwitchProps) {
  return (
    <label className="flex items-center justify-between gap-4 rounded-xl border border-[rgba(139,147,172,0.18)] bg-[#fbfcff] px-4 py-3 dark:border-white/10 dark:bg-[#0f1525]">
      <span className="text-sm font-medium text-[#1b2440] dark:text-white">{label}</span>
      <button
        type="button"
        aria-pressed={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-12 rounded-full transition ${
          checked ? "bg-[#7c4dff]" : "bg-[#d5dbec] dark:bg-[#2a3450]"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${
            checked ? "left-6" : "left-0.5"
          }`}
        />
      </button>
    </label>
  );
}
