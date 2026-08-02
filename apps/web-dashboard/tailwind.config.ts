import type { Config } from "tailwindcss"

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./features/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      colors: {
        background: "#F5F7FA",
        foreground: "#111827",
        surface: "#FFFFFF",
        "surface-2": "#F9FAFB",
        border: "#E5E7EB",
        brand: "#4F46E5",
        brandHover: "#4338CA",
        brandLight: "#EEF2FF",
        muted: "#6B7280",
      },
      fontFamily: {
        sans: ["var(--font-outfit)", "var(--font-inter)", "sans-serif"]
      },
      boxShadow: {
        card: "0 1px 3px 0 rgba(0,0,0,0.06), 0 1px 2px -1px rgba(0,0,0,0.06)",
        "card-hover": "0 4px 16px -2px rgba(79,70,229,0.12), 0 2px 6px -2px rgba(0,0,0,0.06)",
        modal: "0 20px 60px -10px rgba(0,0,0,0.14)"
      },
      keyframes: {
        "pulse-glow": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(79,70,229,0.35)" },
          "50%": { boxShadow: "0 0 0 6px rgba(79,70,229,0)" }
        }
      },
      animation: {
        "pulse-glow": "pulse-glow 2s ease-in-out infinite"
      }
    }
  },
  plugins: []
}
export default config
