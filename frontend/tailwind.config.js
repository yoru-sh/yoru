/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Warm-neutral paper ramp (ink on cream → ink on ember).
        primary: {
          50:  "#faf7f2",
          100: "#f2ece0",
          200: "#e6dcc8",
          300: "#d1c3a6",
          400: "#a89878",
          500: "#7d6e53",
          600: "#5a4e3b",
          700: "#3d342a",
          800: "#25201a",
          900: "#17140f",
          950: "#0f0d0c",
          DEFAULT: "#17140f",
        },
        // Amber accent — thermal-receipt ink fade, single gold for CTAs/links.
        accent: {
          50:  "#fffbeb",
          100: "#fef3c7",
          200: "#fde68a",
          300: "#fcd34d",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
          800: "#92400e",
          900: "#78350f",
          DEFAULT: "#f59e0b",
        },
        // Semantic aliases — CSS-var backed, swap with .dark on <html>.
        paper:   "rgb(var(--bg-page)    / <alpha-value>)",
        surface: "rgb(var(--bg-surface) / <alpha-value>)",
        sunken:  "rgb(var(--bg-sunken)  / <alpha-value>)",
        rule:    "rgb(var(--rule)       / <alpha-value>)",
        ink: {
          DEFAULT: "rgb(var(--ink-primary) / <alpha-value>)",
          muted:   "rgb(var(--ink-muted)   / <alpha-value>)",
          faint:   "rgb(var(--ink-faint)   / <alpha-value>)",
        },
        // Red-flag badge palette — 5 distinct hues, severity gradient
        // wine → red → orange → amber → honey (most severe first).
        flag: {
          secret:    { DEFAULT: "#881337", bg: "#450a1f", fg: "#ffe4e6" }, // rose-900
          env:       { DEFAULT: "#dc2626", bg: "#7f1d1d", fg: "#fee2e2" }, // red-600
          shell:     { DEFAULT: "#ea580c", bg: "#7c2d12", fg: "#ffedd5" }, // orange-600
          migration: { DEFAULT: "#d97706", bg: "#78350f", fg: "#fef3c7" }, // amber-600 (yellow-amber)
          ci:        { DEFAULT: "#ca8a04", bg: "#713f12", fg: "#fef9c3" }, // yellow-600 (amber honey)
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'ui-monospace', '"SF Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        micro:   ['0.6875rem', { lineHeight: '1rem',    letterSpacing: '0.02em' }], // 11
        caption: ['0.8125rem', { lineHeight: '1.125rem' }],                         // 13
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        DEFAULT: "var(--radius-md)",
        lg: "var(--radius-lg)",
      },
      transitionDuration: {
        micro: "120ms",
      },
      keyframes: {
        "feed-in": {
          "0%":   { opacity: "0", transform: "translateY(-2px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "feed-in": "feed-in 200ms ease-out",
      },
    },
  },
  plugins: [],
}
