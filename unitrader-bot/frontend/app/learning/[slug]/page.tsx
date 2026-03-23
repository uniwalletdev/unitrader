"use client";

import { useEffect, useMemo, useState } from "react";
import Head from "next/head";
import { useParams, useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import { api } from "@/lib/api";

type Article = {
  title: string;
  slug: string;
  category: string;
  topic: string;
  content: string;
  reading_time_minutes: number;
  word_count: number;
  related_concept?: string | null;
  published_at?: string | null;
  created_at?: string | null;
};

export default function LearningArticlePage() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug;
  const router = useRouter();

  const [article, setArticle] = useState<Article | null>(null);
  const [related, setRelated] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [articleRes, listRes] = await Promise.all([
          api.get(`/api/learning/articles/${slug}`),
          api.get("/api/learning/articles", { params: { limit: 10, offset: 0 } }),
        ]);
        if (cancelled) return;
        const a: Article = articleRes.data;
        setArticle(a);
        const list: Article[] = listRes.data.articles || listRes.data.data?.articles || [];
        setRelated(list.filter((x) => x.slug !== slug).slice(0, 3));
      } catch (e: any) {
        if (!cancelled) setError(e?.response?.data?.detail || "Failed to load article");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [slug]);

  const description = useMemo(() => {
    if (!article?.content) return "Plain-English trading education from Unitrader AI.";
    const plain = article.content.replace(/\s+/g, " ").trim();
    return plain.slice(0, 160);
  }, [article]);

  const jsonLd = useMemo(
    () =>
      article
        ? {
            "@context": "https://schema.org",
            "@type": "Article",
            headline: article.title,
            author: { "@type": "Person", name: "Unitrader AI" },
          }
        : null,
    [article],
  );

  const shareUrl =
    typeof window !== "undefined"
      ? window.location.href
      : `${process.env.NEXT_PUBLIC_FRONTEND_URL || ""}/learning/${slug}`;

  const twitterHref = `https://twitter.com/intent/tweet?text=${encodeURIComponent(
    article?.title || "Great article from Unitrader AI",
  )}&url=${encodeURIComponent(shareUrl)}`;
  const whatsappHref = `https://wa.me/?text=${encodeURIComponent(
    `${article?.title || "Great article from Unitrader AI"} — ${shareUrl}`,
  )}`;

  return (
    <>
      <Head>
        <title>{article ? `${article.title} | Learn with Unitrader` : "Learning article | Unitrader"}</title>
        <meta name="description" content={description} />
        {jsonLd && (
          <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
        )}
      </Head>
      <div className="min-h-screen bg-dark-950 px-4 py-6 md:px-6">
        <div className="mx-auto max-w-3xl">
          <button
            type="button"
            onClick={() => router.push("/learning")}
            className="mb-4 text-xs text-dark-400 hover:text-brand-400"
          >
            Learning &gt;{" "}
            <span className="text-dark-200">
              {article?.title ? (article.title.length > 48 ? `${article.title.slice(0, 45)}…` : article.title) : "Article"}
            </span>
          </button>

          {loading && (
            <div className="rounded-xl border border-dark-800 bg-dark-950 p-4 text-sm text-dark-400">Loading…</div>
          )}

          {error && !loading && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
          )}

          {article && !loading && !error && (
            <>
              <div className="rounded-2xl border border-dark-800 bg-dark-950 p-5">
                <h1 className="text-xl font-bold text-white md:text-2xl">{article.title}</h1>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-dark-400">
                  <span>{article.reading_time_minutes || 5} min read</span>
                  {article.published_at && (
                    <>
                      <span>•</span>
                      <span>
                        {new Date(article.published_at).toLocaleDateString(undefined, {
                          month: "short",
                          day: "2-digit",
                          year: "numeric",
                        })}
                      </span>
                    </>
                  )}
                  {article.related_concept && (
                    <>
                      <span>•</span>
                      <span>Concept: {article.related_concept}</span>
                    </>
                  )}
                </div>

                <div className="mt-4 prose prose-invert max-w-none prose-p:mb-3 prose-headings:mt-4 prose-headings:mb-2 prose-li:mb-1">
                  <ReactMarkdown>{article.content}</ReactMarkdown>
                </div>

                <div className="mt-6 flex flex-wrap gap-2 text-xs">
                  <span className="text-dark-400">Share this article:</span>
                  <a
                    href={twitterHref}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-full border border-dark-700 px-3 py-1 text-xs text-dark-300 hover:border-sky-500 hover:text-sky-400"
                  >
                    Twitter
                  </a>
                  <a
                    href={whatsappHref}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-full border border-dark-700 px-3 py-1 text-xs text-dark-300 hover:border-green-500 hover:text-green-400"
                  >
                    WhatsApp
                  </a>
                </div>
              </div>

              {related.length > 0 && (
                <div className="mt-6">
                  <div className="mb-3 text-sm font-semibold text-white">Related articles</div>
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    {related.map((r) => (
                      <button
                        key={r.slug}
                        type="button"
                        onClick={() => router.push(`/learning/${r.slug}`)}
                        className="group flex h-full flex-col rounded-xl border border-dark-800 bg-dark-950 p-3 text-left text-xs transition hover:border-brand-500/60 hover:bg-dark-900"
                      >
                        <div className="line-clamp-2 font-semibold text-white group-hover:text-brand-300">
                          {r.title}
                        </div>
                        <div className="mt-1 text-[11px] text-dark-400">
                          {r.reading_time_minutes || 5} min read
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}

