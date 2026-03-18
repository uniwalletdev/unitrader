"use client";

import { useEffect, useState } from "react";
import Head from "next/head";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

type Article = {
  title: string;
  slug: string;
  category: string;
  topic: string;
  reading_time_minutes: number;
  related_concept?: string | null;
  published_at?: string | null;
  created_at?: string | null;
};

function formatDate(iso?: string | null) {
  if (!iso) return "Unpublished";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Unpublished";
  return d.toLocaleDateString(undefined, { month: "short", day: "2-digit", year: "numeric" });
}

function categoryLabel(topic: string) {
  if (topic === "weekly_recap") return "Weekly recap";
  if (topic === "concept_explanation") return "Concept";
  if (topic === "market_update") return "Market update";
  return "Learning";
}

export default function LearningIndexPage() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.get("/api/learning/articles", { params: { limit: 20, offset: 0 } });
        const data = res.data;
        const items: Article[] = data.articles || data.data?.articles || [];
        if (!cancelled) setArticles(items);
      } catch (e: any) {
        if (!cancelled) setError(e?.response?.data?.detail || "Failed to load learning articles");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <Head>
        <title>Learn to trade | Unitrader</title>
        <meta
          name="description"
          content="Plain-English trading education from Apex AI — concepts, recaps, and market insights."
        />
      </Head>
      <div className="min-h-screen bg-dark-950 px-4 py-6 md:px-6">
        <div className="mx-auto flex max-w-5xl flex-col gap-4 md:gap-6">
          <div>
            <h1 className="text-xl font-bold text-white md:text-2xl">Learn with Apex</h1>
            <p className="mt-1 text-sm text-dark-300">
              Plain-English trading education from Apex AI — weekly recaps, core concepts, and market updates.
            </p>
          </div>

          {loading && (
            <div className="rounded-xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-400">
              Loading learning articles…
            </div>
          )}

          {error && !loading && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
          )}

          {!loading && !error && articles.length === 0 && (
            <div className="rounded-xl border border-dark-800 bg-dark-950 p-6 text-sm text-dark-300">
              No learning articles yet. Check back soon — Apex is still writing.
            </div>
          )}

          {articles.length > 0 && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {articles.map((a) => {
                const label = categoryLabel(a.topic);
                const isWeekly = a.topic === "weekly_recap";
                const minutes = a.reading_time_minutes || 5;
                return (
                  <button
                    key={a.slug}
                    type="button"
                    onClick={() => router.push(`/learning/${a.slug}`)}
                    className="group flex h-full flex-col rounded-2xl border border-dark-800 bg-dark-950 p-4 text-left transition hover:border-brand-500/60 hover:bg-dark-900"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-dark-900 px-2 py-0.5 text-[11px] font-semibold text-brand-300">
                        {label}
                      </span>
                      {isWeekly && (
                        <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-300">
                          Based on real Apex trades
                        </span>
                      )}
                    </div>
                    <div className="mt-3 line-clamp-2 text-sm font-semibold text-white md:text-base">
                      {a.title}
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-xs text-dark-400">
                      <span>{minutes} min read</span>
                      <span>•</span>
                      <span>{formatDate(a.published_at || a.created_at)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

