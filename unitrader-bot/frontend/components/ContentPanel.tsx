import { useState, useEffect } from "react";
import {
  BookOpen, FileText, Share2, Loader2, Plus, ExternalLink,
  Check, Clock, Twitter, Linkedin, Instagram, Facebook,
} from "lucide-react";
import { contentApi } from "@/lib/api";

type SubTab = "blog" | "social";

interface BlogPost {
  id: string;
  title: string;
  slug: string;
  status: string;
  content?: string;
  seo_keywords?: string[];
  created_at: string;
  published_at?: string;
}

interface SocialPost {
  id: string;
  platform: string;
  content: string;
  post_type?: string;
  status: string;
  scheduled_at?: string;
  posted_at?: string;
  created_at: string;
}

const PLATFORM_ICON: Record<string, typeof Twitter> = {
  twitter: Twitter,
  linkedin: Linkedin,
  instagram: Instagram,
  facebook: Facebook,
};

const PLATFORM_COLOR: Record<string, string> = {
  twitter: "text-sky-400",
  linkedin: "text-blue-400",
  instagram: "text-pink-400",
  facebook: "text-blue-500",
};

export default function ContentPanel() {
  const [subTab, setSubTab] = useState<SubTab>("blog");
  const [blogPosts, setBlogPosts] = useState<BlogPost[]>([]);
  const [socialPosts, setSocialPosts] = useState<SocialPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [publishing, setPublishing] = useState<string | null>(null);
  const [topic, setTopic] = useState("");
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    setLoading(true);
    setMessage(null);
    if (subTab === "blog") {
      contentApi.blogPosts()
        .then((r) => setBlogPosts(r.data.data?.posts || r.data.data || []))
        .catch(() => setBlogPosts([]))
        .finally(() => setLoading(false));
    } else {
      contentApi.socialPosts()
        .then((r) => setSocialPosts(r.data.data?.posts || r.data.data || []))
        .catch(() => setSocialPosts([]))
        .finally(() => setLoading(false));
    }
  }, [subTab]);

  const handleGenerateBlog = async () => {
    if (!topic.trim()) return;
    setGenerating(true);
    setMessage(null);
    try {
      await contentApi.generateBlog(topic.trim());
      setMessage({ type: "success", text: "Blog post generated! It may take a moment to appear." });
      setTopic("");
      const r = await contentApi.blogPosts();
      setBlogPosts(r.data.data?.posts || r.data.data || []);
    } catch (err: any) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Generation failed." });
    } finally {
      setGenerating(false);
    }
  };

  const handlePublish = async (postId: string) => {
    setPublishing(postId);
    try {
      await contentApi.publishBlog(postId);
      setBlogPosts((prev) => prev.map((p) => p.id === postId ? { ...p, status: "published" } : p));
      setMessage({ type: "success", text: "Post published!" });
    } catch {
      setMessage({ type: "error", text: "Failed to publish." });
    } finally {
      setPublishing(null);
    }
  };

  const handleGenerateSocial = async () => {
    setGenerating(true);
    setMessage(null);
    try {
      await contentApi.generateSocial(topic.trim() || undefined);
      setMessage({ type: "success", text: "Social posts generated!" });
      setTopic("");
      const r = await contentApi.socialPosts();
      setSocialPosts(r.data.data?.posts || r.data.data || []);
    } catch (err: any) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Generation failed." });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <BookOpen size={18} className="text-brand-400" />
        <h1 className="text-xl font-bold text-white">Content</h1>
      </div>

      {/* Sub-tabs */}
      <div className="flex gap-1 rounded-lg bg-dark-900 p-1">
        {(["blog", "social"] as SubTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setSubTab(t)}
            className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition ${
              subTab === t ? "bg-dark-800 text-white" : "text-dark-400 hover:text-dark-200"
            }`}
          >
            {t === "blog" ? <FileText size={14} /> : <Share2 size={14} />}
            {t === "blog" ? "Blog Posts" : "Social Posts"}
          </button>
        ))}
      </div>

      {message && (
        <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs ${
          message.type === "success" ? "bg-brand-500/10 text-brand-400" : "bg-red-500/10 text-red-400"
        }`}>
          {message.text}
        </div>
      )}

      {/* Generate form */}
      <div className="flex gap-2">
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !generating && (subTab === "blog" ? handleGenerateBlog() : handleGenerateSocial())}
          placeholder={subTab === "blog" ? "Enter a blog topic..." : "Enter a topic (optional)..."}
          className="input flex-1"
          disabled={generating}
        />
        <button
          onClick={subTab === "blog" ? handleGenerateBlog : handleGenerateSocial}
          disabled={generating || (subTab === "blog" && !topic.trim())}
          className="btn-primary gap-2 whitespace-nowrap px-4 disabled:opacity-50"
        >
          {generating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          {generating ? "Generating..." : subTab === "blog" ? "Generate Blog" : "Generate Posts"}
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-sm text-dark-500">
          <Loader2 size={16} className="mr-2 animate-spin" /> Loading...
        </div>
      ) : subTab === "blog" ? (
        blogPosts.length === 0 ? (
          <div className="py-16 text-center text-sm text-dark-500">
            No blog posts yet. Generate your first one above.
          </div>
        ) : (
          <div className="space-y-3">
            {blogPosts.map((post) => (
              <div key={post.id} className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-sm font-medium text-white">{post.title}</h3>
                    <div className="mt-1 flex items-center gap-3 text-xs text-dark-500">
                      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        post.status === "published"
                          ? "bg-brand-500/10 text-brand-400"
                          : "bg-yellow-500/10 text-yellow-400"
                      }`}>
                        {post.status === "published" ? <Check size={9} /> : <Clock size={9} />}
                        {post.status}
                      </span>
                      <span>{new Date(post.created_at).toLocaleDateString()}</span>
                      {post.seo_keywords && post.seo_keywords.length > 0 && (
                        <span className="truncate text-dark-600">{post.seo_keywords.join(", ")}</span>
                      )}
                    </div>
                  </div>
                  {post.status === "draft" && (
                    <button
                      onClick={() => handlePublish(post.id)}
                      disabled={publishing === post.id}
                      className="flex shrink-0 items-center gap-1 rounded-md border border-brand-500/30 px-3 py-1.5 text-xs text-brand-400 transition hover:bg-brand-500/10 disabled:opacity-50"
                    >
                      {publishing === post.id ? <Loader2 size={11} className="animate-spin" /> : <ExternalLink size={11} />}
                      Publish
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )
      ) : (
        socialPosts.length === 0 ? (
          <div className="py-16 text-center text-sm text-dark-500">
            No social posts yet. Generate some above.
          </div>
        ) : (
          <div className="space-y-3">
            {socialPosts.map((post) => {
              const PlatformIcon = PLATFORM_ICON[post.platform] || Share2;
              const color = PLATFORM_COLOR[post.platform] || "text-dark-400";
              return (
                <div key={post.id} className="rounded-xl border border-dark-800 bg-dark-950 p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <PlatformIcon size={14} className={color} />
                    <span className={`text-xs font-medium capitalize ${color}`}>{post.platform}</span>
                    {post.post_type && (
                      <span className="rounded-full bg-dark-800 px-2 py-0.5 text-[10px] text-dark-400">{post.post_type}</span>
                    )}
                    <span className="ml-auto text-xs text-dark-600">{new Date(post.created_at).toLocaleDateString()}</span>
                  </div>
                  <p className="text-sm leading-relaxed text-dark-300">{post.content}</p>
                </div>
              );
            })}
          </div>
        )
      )}
    </div>
  );
}
