/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dark theme tuned for a financial dashboard: high contrast for
        // numbers (PnL red/green), muted chrome.
        bg: { DEFAULT: '#0b1220', panel: '#121a2b', muted: '#1c2741' },
        edge: '#2a3554',
        text: { DEFAULT: '#e6ecf7', muted: '#8a96b3' },
        up: '#16c784',     // gains
        down: '#ea3943',   // losses
        accent: '#3b82f6',
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};
