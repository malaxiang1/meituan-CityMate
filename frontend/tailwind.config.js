/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#24302f",
        moss: "#47624f",
        mint: "#dcefe6",
        coral: "#dd6b4d",
        butter: "#f5ca62",
        paper: "#f7f5ef",
      },
      boxShadow: {
        panel: "0 16px 50px rgba(40, 50, 45, 0.10)",
      },
    },
  },
  plugins: [],
};

