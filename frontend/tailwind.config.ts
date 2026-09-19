import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        muted: "hsl(var(--muted))",
        primary: "hsl(var(--primary))",
        accent: "hsl(var(--accent))",
        card: "hsl(var(--card))"
      },
      boxShadow: {
        panel: "0 24px 80px rgba(1, 6, 16, 0.24)",
        soft: "0 14px 30px rgba(9, 12, 21, 0.12)"
      },
      backgroundImage: {
        mesh:
          "radial-gradient(circle at top left, rgba(82, 255, 168, 0.18), transparent 35%), radial-gradient(circle at top right, rgba(45, 112, 255, 0.14), transparent 32%), linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0))"
      }
    }
  },
  plugins: []
};

export default config;
