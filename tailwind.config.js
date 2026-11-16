/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#172b4d',
        muted: '#718096',
        brand: '#2463eb',
        'brand-dark': '#1849b8',
        canvas: '#f5f8fc',
      },
      fontFamily: {
        sans: ['DM Sans', 'sans-serif'],
        display: ['Manrope', 'sans-serif'],
      },
      boxShadow: {
        card: '0 8px 28px rgba(31, 56, 90, 0.06)',
      },
    },
  },
  plugins: [],
}
