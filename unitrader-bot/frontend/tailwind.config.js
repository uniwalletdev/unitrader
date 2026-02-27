/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
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
          700: "#455162",
          800: "#3c4553",
          900: "#353c47",
          950: "#0d1117",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      animation: {
        "fade-in": "fadeIn 0.5s ease-in-out",
        "slide-up": "slideUp 0.5s ease-out",
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        ticker: "ticker 20s linear infinite",
      },
      keyframes: {
        fadeIn: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp: { "0%": { opacity: "0", transform: "translateY(20px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
        ticker: { "0%": { transform: "translateX(0)" }, "100%": { transform: "translateX(-50%)" } },
      },
    },
  },
  plugins: [],
};
