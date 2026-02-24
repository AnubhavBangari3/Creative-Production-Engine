"use client";

import { useEffect, useMemo, useState } from "react";
import axios from "axios";

type ShortItem = { title: string; script: string };

type Kit = {
  topic: string;
  tone: string;
  language: string;
  hooks: any;
  titles: any;
  description: any;
  tags: any;
  thumbnail: any;
  shorts: any;
  script: any;
  error?: string;
  raw?: string;
  fixed?: string;
  hint?: string;
};

type RecentItem = {
  id: number;
  topic: string;
  tone: string;
  language: string;
  created_at: string;
};

const API_BASE = "http://127.0.0.1:8000/api";

const toStringArray = (v: any): string[] => {
  if (!v) return [];

  // 1) If it's already an array
  if (Array.isArray(v)) {
    return v
      .map((item) => {
        if (typeof item === "string") return item;

        // if LLM returns objects like { title: "..."} or { text: "..." }
        if (item && typeof item === "object") {
          if (typeof (item as any).title === "string") return (item as any).title;
          if (typeof (item as any).text === "string") return (item as any).text;

          // last-resort: join string values
          const vals = Object.values(item)
            .filter((x) => typeof x === "string")
            .join(" ");
          return vals || "";
        }

        return String(item);
      })
      .map((s) => s.trim())
      .filter(Boolean);
  }

  // 2) If it's a string (comma/newline separated)
  if (typeof v === "string") {
    return v
      .split(/\r?\n|,/g)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  // 3) If it's an object with a list inside (sometimes LLM returns { items: [...] })
  if (typeof v === "object") {
    const possible = (v as any).items || (v as any).titles || (v as any).hooks || (v as any).tags;
    if (Array.isArray(possible)) return toStringArray(possible);
  }

  return [];
};

const toShortsArray = (v: any): ShortItem[] => {
  if (!Array.isArray(v)) return [];
  return v
    .map((x) => ({
      title: typeof x?.title === "string" ? x.title : "",
      script: typeof x?.script === "string" ? x.script : "",
    }))
    .filter((x) => x.title || x.script);
};

const toThumbnail = (v: any): { text: string; prompt: string } => {
  if (!v || typeof v !== "object") return { text: "", prompt: "" };
  return {
    text: typeof (v as any).text === "string" ? (v as any).text : "",
    prompt: typeof (v as any).prompt === "string" ? (v as any).prompt : "",
  };
};

// ✅ NEW: only accept non-empty strings; supports nested response shapes
const pickNonEmptyString = (value: any): string | null => {
  if (typeof value === "string") {
    const s = value.trim();
    return s.length ? s : null;
  }
  if (value && typeof value === "object") {
    const candidates = [
      (value as any).script,
      (value as any).text,
      (value as any).content,
      (value as any).value,
    ];
    for (const c of candidates) {
      if (typeof c === "string" && c.trim().length) return c.trim();
    }
  }
  return null;
};

// ✅ NEW: don’t overwrite thumbnail fields if new ones are empty/missing
const normalizeThumbnail = (
  value: any,
  prevThumb?: { text: string; prompt: string }
): { text: string; prompt: string } => {
  const prev = prevThumb ?? { text: "", prompt: "" };

  // backend returns a string => treat as prompt
  if (typeof value === "string") {
    const p = value.trim();
    return {
      text: prev.text,
      prompt: p.length ? p : prev.prompt,
    };
  }

  // backend returns an object
  if (value && typeof value === "object") {
    const text =
      typeof (value as any).text === "string" && (value as any).text.trim().length
        ? (value as any).text.trim()
        : prev.text;

    const prompt =
      typeof (value as any).prompt === "string" && (value as any).prompt.trim().length
        ? (value as any).prompt.trim()
        : prev.prompt;

    return { text, prompt };
  }

  return prev;
};

const formatDateTime = (iso: string) => {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
};

const classNames = (...xs: Array<string | false | null | undefined>) =>
  xs.filter(Boolean).join(" ");

export default function Home() {
  const [topic, setTopic] = useState("");
  const [kit, setKit] = useState<Kit | null>(null);
  const [loading, setLoading] = useState(false);

  const [recent, setRecent] = useState<RecentItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const fetchRecent = async () => {
    try {
      const res = await axios.get(`${API_BASE}/kits/recent/?limit=5`);
      setRecent(res.data?.results ?? []);
    } catch {
      setRecent([]);
    }
  };

  useEffect(() => {
    fetchRecent();
  }, []);

  const loadKitById = async (id: number) => {
    setSelectedId(id);
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/kits/${id}/`);
      const loadedKit = res.data?.kit;
      if (loadedKit) setKit(loadedKit);
    } catch {
      alert("Failed to load kit");
    } finally {
      setLoading(false);
    }
  };

  const generate = async () => {
    if (!topic.trim()) return;
    setLoading(true);
    setKit(null);
    setSelectedId(null);

    try {
      const res = await axios.post(`${API_BASE}/generate/`, {
        topic: topic.trim(),
        tone: "cinematic",
        language: "English",
      });

      setKit(res.data);
      fetchRecent();
    } catch (e: any) {
      setKit({
        topic,
        tone: "cinematic",
        language: "English",
        hooks: [],
        titles: [],
        description: "",
        tags: [],
        thumbnail: { text: "", prompt: "" },
        shorts: [],
        script: "",
        error: "Frontend could not call backend",
        raw: e?.message || "Unknown error",
      });
    } finally {
      setLoading(false);
    }
  };

  const regenerate = async (section: string) => {
    if (!kit) return;
    setLoading(true);

    try {
      const res = await axios.post(`${API_BASE}/regenerate/`, {
        section,
        kit,
      });

      const sec = res.data?.section;
      const value = res.data?.value;

      setKit((prev) => {
        if (!prev) return prev;

        if (res.data?.error) {
          return { ...prev, error: res.data.error, raw: res.data.raw, fixed: res.data.fixed };
        }

        if (sec === "hooks" || sec === "titles" || sec === "tags") {
          const arr = toStringArray(value);
          // ✅ don't wipe if empty array comes back
          return arr.length ? { ...prev, [sec]: arr } : prev;
        }

        if (sec === "shorts") {
          const arr = toShortsArray(value);
          return arr.length ? { ...prev, shorts: arr } : prev;
        }

        if (sec === "thumbnail") {
          // ✅ don’t erase prompt/text if backend returns empty
          return {
            ...prev,
            thumbnail: normalizeThumbnail(value, toThumbnail(prev.thumbnail)),
          };
        }

        if (sec === "script" || sec === "description") {
          const next = pickNonEmptyString(value);
          // ✅ don't erase old content if backend returns empty
          return next ? { ...prev, [sec]: next } : prev;
        }

        return prev;
      });
    } catch {
      alert("Regenerate failed");
    } finally {
      setLoading(false);
    }
  };

  const exportKit = async () => {
    if (!kit) return;
    const res = await axios.post(`${API_BASE}/export/`, kit, { responseType: "blob" });
    const blob = new Blob([res.data], { type: "text/plain" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(kit.topic || "kit").replace(/\s+/g, "_")}_kit.txt`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const hooks = useMemo(() => toStringArray(kit?.hooks), [kit]);
  const titles = useMemo(() => toStringArray(kit?.titles), [kit]);
  const tags = useMemo(() => toStringArray(kit?.tags), [kit]);
  const shorts = useMemo(() => toShortsArray(kit?.shorts), [kit]);
  const thumbnail = useMemo(() => toThumbnail(kit?.thumbnail), [kit]);
  const description = typeof kit?.description === "string" ? kit.description : "";
  const script =
    typeof kit?.script === "string" && kit.script.trim().length
      ? kit.script
      : "-";

  return (
    <main className="min-h-screen bg-gradient-to-b from-slate-50 to-white text-slate-900">
      {/* Loading Overlay */}
      {loading && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/20 backdrop-blur-sm">
          <div className="rounded-2xl bg-white shadow-xl border border-slate-200 px-6 py-5 flex items-center gap-3">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900" />
            <div>
              <p className="font-semibold">Working…</p>
              <p className="text-sm text-slate-600">Generating / loading content</p>
            </div>
          </div>
        </div>
      )}

      <div className="mx-auto max-w-[1400px] px-6 py-8">
        {/* Top Header */}
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              Creative Production Engine
            </h1>
            <p className="mt-1 text-slate-600">
              One topic in → publish-ready content kit out (local AI, no paid APIs)
            </p>
          </div>

          <div className="hidden md:flex items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-700 shadow-sm">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              Demo-ready
            </span>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-6">
          {/* Sidebar */}
          <aside className="col-span-12 md:col-span-4 lg:col-span-3">
            <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="p-4 border-b border-slate-200">
                <div className="flex items-center justify-between">
                  <h2 className="font-semibold">Recent Kits</h2>
                  <button
                    onClick={fetchRecent}
                    className="text-sm font-medium text-slate-600 hover:text-slate-900"
                  >
                    Refresh
                  </button>
                </div>
                <p className="mt-1 text-sm text-slate-500">
                  Click to load a previous kit.
                </p>
              </div>

              <div className="p-2">
                {recent.length === 0 ? (
                  <div className="p-4 text-sm text-slate-600">
                    No history yet. Generate your first kit.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {recent.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => loadKitById(item.id)}
                        className={classNames(
                          "w-full text-left rounded-xl border px-3 py-3 transition shadow-sm",
                          "hover:shadow-md hover:border-slate-300",
                          selectedId === item.id
                            ? "border-slate-900 bg-slate-900 text-white"
                            : "border-slate-200 bg-white text-slate-900"
                        )}
                      >
                        <div className="font-semibold leading-snug">
                          {item.topic.length > 64 ? item.topic.slice(0, 64) + "…" : item.topic}
                        </div>
                        <div
                          className={classNames(
                            "mt-1 text-xs",
                            selectedId === item.id ? "text-white/80" : "text-slate-500"
                          )}
                        >
                          {formatDateTime(item.created_at)}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </aside>

          {/* Main */}
          <section className="col-span-12 md:col-span-8 lg:col-span-9">
            {/* Sticky input bar */}
            <div className="sticky top-4 z-10">
              <div className="rounded-2xl border border-slate-200 bg-white/90 backdrop-blur shadow-sm">
                <div className="p-4">
                  <div className="flex flex-col lg:flex-row gap-3">
                    <div className="flex-1">
                      <label className="text-sm font-medium text-slate-700">
                        Topic
                      </label>
                      <input
                        value={topic}
                        onChange={(e) => setTopic(e.target.value)}
                        placeholder="e.g. Why AI will change education"
                        className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm outline-none focus:border-slate-400 focus:ring-4 focus:ring-slate-100"
                      />
                    </div>

                    <div className="flex items-end gap-2">
                      <button
                        onClick={generate}
                        disabled={!topic.trim() || loading}
                        className={classNames(
                          "rounded-xl px-5 py-3 font-semibold shadow-sm transition",
                          !topic.trim() || loading
                            ? "bg-slate-200 text-slate-500 cursor-not-allowed"
                            : "bg-slate-900 text-white hover:bg-slate-800"
                        )}
                      >
                        Generate Kit
                      </button>

                      {kit && !kit.error && (
                        <button
                          onClick={exportKit}
                          className="rounded-xl px-5 py-3 font-semibold shadow-sm transition bg-emerald-600 text-white hover:bg-emerald-700"
                        >
                          Export
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Action row */}
                  {kit && !kit.error && (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {[
                        ["hooks", "Regenerate Hooks"],
                        ["titles", "Regenerate Titles"],
                        ["thumbnail", "Regenerate Thumbnail"],
                        ["shorts", "Regenerate Shorts"],
                        ["script", "Regenerate Script"],
                      ].map(([key, label]) => (
                        <button
                          key={key}
                          onClick={() => regenerate(key)}
                          className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-800 shadow-sm hover:border-slate-300 hover:shadow transition"
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Error block */}
            {kit?.error && (
              <div className="mt-6 rounded-2xl border border-red-200 bg-red-50 shadow-sm">
                <div className="p-5">
                  <p className="font-bold text-red-800">Error</p>
                  <pre className="mt-2 whitespace-pre-wrap text-sm text-red-900">
                    {kit.error}
                  </pre>

                  {kit.hint && (
                    <>
                      <p className="font-bold text-red-800 mt-4">Hint</p>
                      <pre className="mt-2 whitespace-pre-wrap text-sm text-red-900">
                        {kit.hint}
                      </pre>
                    </>
                  )}

                  {kit.raw && (
                    <>
                      <p className="font-bold text-red-800 mt-4">Raw Output</p>
                      <pre className="mt-2 whitespace-pre-wrap text-xs text-red-900">
                        {kit.raw}
                      </pre>
                    </>
                  )}

                  {kit.fixed && (
                    <>
                      <p className="font-bold text-red-800 mt-4">Fixed Output</p>
                      <pre className="mt-2 whitespace-pre-wrap text-xs text-red-900">
                        {kit.fixed}
                      </pre>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* Output */}
            {kit && !kit.error && (
              <div className="mt-6 space-y-6">
                <Card title="Hooks" subtitle="Open with curiosity. First 3 seconds matter.">
                  <ul className="list-disc pl-6 space-y-1">
                    {hooks.map((h, i) => (
                      <li key={i} className="text-slate-800">
                        {h}
                      </li>
                    ))}
                  </ul>
                </Card>

                <Card title="Titles" subtitle="High CTR titles with clarity + intrigue.">
                  <ul className="list-disc pl-6 space-y-1">
                    {titles.map((t, i) => (
                      <li key={i} className="text-slate-800">
                        {t}
                      </li>
                    ))}
                  </ul>
                </Card>

                <Card title="Description" subtitle="SEO + clarity. Add CTA at the end.">
                  <p className="text-slate-800 leading-relaxed">{description || "-"}</p>
                </Card>

                <Card title="Tags" subtitle="Copy-paste ready tags.">
                  <p className="text-slate-800">
                    {tags.length ? tags.join(", ") : "-"}
                  </p>
                </Card>

                <Card title="Thumbnail" subtitle="Text + image prompt for your generator tool.">
                  <div className="space-y-2">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                      <p className="text-sm text-slate-600">Text</p>
                      <p className="font-semibold text-slate-900">
                        {thumbnail.text || "-"}
                      </p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                      <p className="text-sm text-slate-600">Prompt</p>
                      <p className="text-slate-900">{thumbnail.prompt || "-"}</p>
                    </div>
                  </div>
                </Card>

                <Card title="Shorts" subtitle="5 short scripts optimized for retention.">
                  {shorts.length === 0 ? (
                    <p className="text-slate-700">-</p>
                  ) : (
                    <div className="space-y-3">
                      {shorts.map((s, i) => (
                        <div key={i} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                          <p className="font-semibold text-slate-900">{s.title}</p>
                          <pre className="mt-2 whitespace-pre-wrap text-sm text-slate-800 leading-relaxed">
                            {s.script}
                          </pre>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>

                <Card title="Script" subtitle="Long-form voiceover script.">
                  <pre className="whitespace-pre-wrap text-sm text-slate-800 leading-relaxed">
                    {script}
                  </pre>
                </Card>
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

function Card({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="p-5 border-b border-slate-200">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{title}</h2>
            {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
          </div>
        </div>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}