import Head from "next/head";
import Link from "next/link";
import React from "react";

type LegalLayoutProps = {
  title: string;
  lastUpdated: string;
  children: React.ReactNode;
};

export default function LegalLayout({ title, lastUpdated, children }: LegalLayoutProps) {
  return (
    <>
      <Head>
        <title>{title} — Unitrader</title>
        <meta name="robots" content="index, follow" />
      </Head>

      <style jsx global>{`
        .legal-prose h2 {
          font-size: 16px;
          font-weight: 700;
          color: #ffffff;
          margin-top: 32px;
          margin-bottom: 8px;
        }
        .legal-prose h3 {
          font-size: 14px;
          font-weight: 700;
          color: #d1d5db;
          margin-top: 20px;
          margin-bottom: 6px;
        }
        .legal-prose p {
          font-size: 14px;
          color: #9ca3af;
          line-height: 1.75;
          margin-bottom: 12px;
        }
        .legal-prose ul {
          font-size: 14px;
          color: #9ca3af;
          line-height: 1.75;
          list-style: disc;
          padding-left: 24px;
          margin-bottom: 12px;
        }
        .legal-prose li {
          margin-bottom: 4px;
        }
        .legal-prose a {
          color: #22c55e;
          text-decoration: none;
        }
        .legal-prose a:hover {
          text-decoration: underline;
        }
        .legal-prose strong {
          color: #e8eaed;
          font-weight: 600;
        }
      `}</style>

      <div style={{ minHeight: "100vh", backgroundColor: "#080a0f" }}>
        <div
          style={{
            maxWidth: "720px",
            margin: "0 auto",
            padding: "48px 24px",
          }}
          className="px-4 py-6 sm:px-6 sm:py-12"
        >
          {/* Back link */}
          <div style={{ marginBottom: "32px" }}>
            <Link
              href="/"
              style={{
                fontSize: "12px",
                color: "#6b7280",
                textDecoration: "none",
              }}
              className="hover:text-white transition-colors"
            >
              ← Back to Unitrader
            </Link>
          </div>

          {/* Page heading */}
          <h1
            style={{
              fontSize: "28px",
              fontWeight: 700,
              color: "#ffffff",
              margin: "0 0 8px 0",
            }}
          >
            {title}
          </h1>

          {/* Last updated */}
          <p
            style={{
              fontSize: "12px",
              color: "#6b7280",
              margin: "0 0 20px 0",
            }}
          >
            Last updated: {lastUpdated}
          </p>

          {/* Divider */}
          <hr
            style={{
              border: "none",
              borderTop: "1px solid #1e2330",
              marginBottom: "32px",
            }}
          />

          {/* Children with prose styles */}
          <div className="legal-prose">{children}</div>

          {/* Footer strip */}
          <div
            style={{
              marginTop: "48px",
              borderTop: "1px solid #1e2330",
              paddingTop: "16px",
              textAlign: "center",
              fontSize: "11px",
              color: "#374151",
            }}
          >
            Universal Wallet Ltd — Company No. 16695347 — ICO Ref: ZC068643
          </div>
        </div>
      </div>
    </>
  );
}
