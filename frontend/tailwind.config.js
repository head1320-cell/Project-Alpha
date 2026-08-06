/** @type {import('tailwindcss').Config} */
module.exports = {
  // 다크는 `.dark` 클래스로만 켠다 — 매체 질의(media)로 두면 OS 설정만으로
  // 아직 대응되지 않은 라우트까지 다크로 넘어가 버린다(globals.css §47 참고).
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Geist", "system-ui", "-apple-system", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SF Mono", "monospace"],
      },
      colors: {
        // Variant Institutional Terminal tokens
        terminal: {
          bg: "#ffffff",
          surface: "#fafafa",
          border: "#e5e5e5",
          accent: "#1200ff",
          ink: "#111111",
          muted: "#71717a",
        },
      },
      animation: {
        "fade-in":   "fadeIn 0.25s ease-out",
        "slide-up":  "slideUp 0.3s ease-out",
        "pulse-dot": "pulseDot 2s ease-in-out infinite",
      },
      keyframes: {
        fadeIn:   { from: { opacity: 0 }, to: { opacity: 1 } },
        slideUp:  { from: { transform: "translateY(8px)", opacity: 0 }, to: { transform: "translateY(0)", opacity: 1 } },
        pulseDot: { "0%,100%": { opacity: 1 }, "50%": { opacity: 0.4 } },
      },
    },
  },
  plugins: [],
};
