/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Segoe UI"', 'Tahoma', '"Noto Kufi Arabic"', 'Arial', 'sans-serif'],
      },
      colors: {
        // هوية «أثير»: زمرّد عميق + ذهبي رملي
        atheer: {
          50: '#eefaf6',
          100: '#d7f2e7',
          500: '#0e9f6e',
          600: '#0b7f59',
          700: '#0a6849',
          800: '#08543c',
          900: '#06392a',
          950: '#03231a',
        },
        gold: { 400: '#e8c766', 500: '#d4af37', 600: '#b8941f' },
      },
    },
  },
  plugins: [],
}
