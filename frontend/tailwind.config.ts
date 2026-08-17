import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "monospace"],
        display: ["Cal Sans", "var(--font-geist-sans)", "system-ui", "sans-serif"],
      },
      letterSpacing: {
        tightest: "-0.03em",
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // Status colors for pipeline
        status: {
          new: "hsl(var(--status-new))",
          review: "hsl(var(--status-review))",
          approved: "hsl(var(--status-approved))",
          sent: "hsl(var(--status-sent))",
          replied: "hsl(var(--status-replied))",
          rejected: "hsl(var(--status-rejected))",
        },
        // Signature accent
        accent1: "hsl(var(--accent-1))",
        accent2: "hsl(var(--accent-2))",
      },
      borderRadius: {
        lg: "var(--radius-lg)",
        md: "var(--radius-md)",
        sm: "var(--radius-sm)",
        xl: "var(--radius-xl)",
        "2xl": "var(--radius-2xl)",
      },
      boxShadow: {
        card: "0px 1px 3px 0px rgba(0,0,0,0.04), 0px 8px 24px -8px rgba(0,0,0,0.08)",
        "card-hover":
          "0px 2px 4px 0px rgba(0,0,0,0.05), 0px 16px 40px -12px rgba(0,0,0,0.14)",
        "elevation-low":
          "0px 1px 1px 0px rgba(0,0,0,0.07), 0px 1px 2px 0px rgba(0,0,0,0.08), 0px 2px 2px 0px rgba(0,0,0,0.10), 0px 0px 8px 0px rgba(0,0,0,0.05)",
        dropdown:
          "0px 5px 20px 0px rgba(0,0,0,0.10), 0px 10px 40px 0px rgba(0,0,0,0.03)",
        "button-brand":
          "0px 2px 3px 0px rgba(0,0,0,0.06), 0px 1px 1px 0px rgba(0,0,0,0.08), 1px 4px 8px 0px rgba(0,0,0,0.12), 0px 2px 0.4px 0px rgba(255,255,255,0.12) inset, 0px -3px 2px 0px rgba(0,0,0,0.04) inset",
        "button-brand-hover":
          "0px 1px 1px 0px rgba(0,0,0,0.10), 0px 2px 3px 0px rgba(0,0,0,0.08), 1px 4px 8px 0px rgba(0,0,0,0.12), 0px -3px 2px 0px rgba(0,0,0,0.10) inset, 0px 2px 0.4px 0px rgba(255,255,255,0.24) inset",
        "button-brand-active":
          "0px 3px 1px 0px rgba(0,0,0,0.10) inset, 0px 0px 2px 0px rgba(0,0,0,0.10) inset",
      },
      keyframes: {
        "fade-in-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in-right": {
          "0%": { transform: "translateX(100%)" },
          "100%": { transform: "translateX(0)" },
        },
      },
      animation: {
        "fade-in-up": "fade-in-up 0.4s cubic-bezier(0.21, 1.02, 0.73, 1) forwards",
        "slide-in-right": "slide-in-right 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },
  plugins: [],
};

export default config;
