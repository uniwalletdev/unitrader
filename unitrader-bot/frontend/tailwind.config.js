/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  "#eefff4",
          100: "#d7ffe8",
          200: "#b2ffd4",
          300: "#76ffb2",
          400: "#33f58a",
          500: "#0adb6a",
          600: "#00b654",
          700: "#008f44",
          800: "#047038",
          900: "#065c30",
          950: "#013318",
        },
        dark: {
          50:  "#f6f7f9",
          100: "#eceef2",
          200: "#d5d9e2",
          300: "#b2bbc8",
          400: "#8896aa",
          500: "#697a90",
          600: "#546378",
          700: "#3a4553",
          800: "#1e2632",
          900: "#151b23",
          950: "#06080d",
        },
      },
      fontFamily: {
        sans: ["DM Sans", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      borderRadius: {
        "2xl": "16px",
      },
      animation: {
        "fade-in": "fadeIn 0.4s ease-out",
        "slide-up": "slideUp 0.4s ease-out",
        "slide-down": "slideDown 0.3s ease-out",
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "pulse-glow": "pulseGlow 2s ease-in-out infinite",
        ticker: "ticker 20s linear infinite",
        "spin-slow": "spin 2s linear infinite",
      },
      keyframes: {
        fadeIn: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp: { "0%": { opacity: "0", transform: "translateY(12px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
        slideDown: { "0%": { opacity: "0", transform: "translateY(-8px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
        pulseGlow: { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.6" } },
        ticker: { "0%": { transform: "translateX(0)" }, "100%": { transform: "translateX(-50%)" } },
      },
      boxShadow: {
        "glow-sm": "0 0 15px rgba(10, 219, 106, 0.1)",
        "glow-md": "0 0 30px rgba(10, 219, 106, 0.15)",
        "glow-lg": "0 0 60px rgba(10, 219, 106, 0.1)",
        "card": "0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)",
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};
