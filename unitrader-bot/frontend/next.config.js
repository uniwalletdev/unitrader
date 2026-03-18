/** @type {import('next').NextConfig} */
const isCapacitor = process.env.CAPACITOR === "true";

const nextConfig = {
  reactStrictMode: true,
  ...(isCapacitor ? { output: "export" } : {}),
  ...(isCapacitor ? { images: { unoptimized: true }, trailingSlash: true } : {}),
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    NEXT_PUBLIC_STRIPE_PUBLIC_KEY: process.env.NEXT_PUBLIC_STRIPE_PUBLIC_KEY || "",
  },
};

module.exports = nextConfig;
