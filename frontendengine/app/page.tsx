"use client";

import { useState } from "react";
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

const API_BASE = "http://127.0.0.1:8000/api";

const toStringArray = (v: any): string[] => {
  if (Array.isArray(v)) return v.map((x) => String(x));
  if (typeof v === "string") {
    return v
      .split(/\r?\n|,/g)
      .map((s) => s.trim())
      .filter(Boolean);
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
    text: typeof v.text === "string" ? v.text : "",
    prompt: typeof v.prompt === "string" ? v.prompt : "",
  };
};

export default function Home() {
  const [topic, setTopic] = useState("");
  const [kit, setKit] = useState<Kit | null>(null);
  const [loading, setLoading] = useState(false);

  const generate = async () => {
    if (!topic.trim()) return;
    setLoading(true);
    setKit(null);

    try {
      const res = await axios.post(`${API_BASE}/generate/`, {
        topic: topic.trim(),
        tone: "cinematic",
        language: "English",
      });

      setKit(res.data);
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

      // expected: { section: "titles", value: [...] }
      const sec = res.data?.section;
      const value = res.data?.value;

      setKit((prev) => {
        if (!prev) return prev;

        // If backend returned an error payload, store it
        if (res.data?.error) {
          return { ...prev, error: res.data.error, raw: res.data.raw, fixed: res.data.fixed };
        }

        if (sec === "hooks" || sec === "titles" || sec === "tags") {
          return { ...prev, [sec]: toStringArray(value) };
        }

        if (sec === "shorts") {
          return { ...prev, shorts: toShortsArray(value) };
        }

        if (sec === "thumbnail") {
          return { ...prev, thumbnail: toThumbnail(value) };
        }

        if (sec === "script" || sec === "description") {
          return { ...prev, [sec]: typeof value === "string" ? value : "" };
        }

        return prev;
      });
    } catch (e) {
      alert("Regenerate failed");
    } finally {
      setLoading(false);
    }
  };

  const hooks = toStringArray(kit?.hooks);
  const titles = toStringArray(kit?.titles);
  const tags = toStringArray(kit?.tags);
  const shorts = toShortsArray(kit?.shorts);
  const thumbnail = toThumbnail(kit?.thumbnail);
  const description = typeof kit?.description === "string" ? kit.description : "";
  const script = typeof kit?.script === "string" ? kit.script : "";

  return (
    <main className="min-h-screen p-10">
      <h1 className="text-3xl font-bold mb-6">Creative Production Engine</h1>

      <div className="flex gap-3 mb-4">
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Enter a topic..."
          className="border px-3 py-2 rounded w-full"
        />
        <button
          onClick={generate}
          disabled={!topic.trim() || loading}
          className="px-4 py-2 bg-black text-white rounded"
        >
          {loading ? "Generating..." : "Generate Kit"}
        </button>
      </div>

      {/* Regenerate Buttons */}
      {kit && !kit.error && (
        <div className="flex flex-wrap gap-2 mb-6">
          <button onClick={() => regenerate("hooks")} className="px-3 py-2 border rounded">
            Regenerate Hooks
          </button>
          <button onClick={() => regenerate("titles")} className="px-3 py-2 border rounded">
            Regenerate Titles
          </button>
          <button onClick={() => regenerate("thumbnail")} className="px-3 py-2 border rounded">
            Regenerate Thumbnail
          </button>
          <button onClick={() => regenerate("shorts")} className="px-3 py-2 border rounded">
            Regenerate Shorts
          </button>
          <button onClick={() => regenerate("script")} className="px-3 py-2 border rounded">
            Regenerate Script
          </button>
        </div>
      )}

      {kit && !kit.error && (
  <button
    onClick={async () => {
      const res = await axios.post(`${API_BASE}/export/`, kit, { responseType: "blob" });
      const blob = new Blob([res.data], { type: "text/plain" });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(kit.topic || "kit").replace(/\s+/g, "_")}_kit.txt`;
      a.click();
      window.URL.revokeObjectURL(url);
    }}
    className="px-4 py-2 bg-green-600 text-white rounded"
  >
    Export Kit (.txt)
  </button>
)}

{/* <div className="flex gap-2 mb-3">
  <button className="px-3 py-1 border rounded" onClick={() => setTopic("Why AI will change education")}>Demo 1</button>
  <button className="px-3 py-1 border rounded" onClick={() => setTopic("How inflation affects daily life")}>Demo 2</button>
  <button className="px-3 py-1 border rounded" onClick={() => setTopic("The real reason habits are hard to change")}>Demo 3</button>
</div> */}

      {/* Error block */}
      {kit?.error && (
        <div className="p-4 border rounded bg-red-50 mb-6">
          <p className="font-bold">Error:</p>
          <pre className="whitespace-pre-wrap">{kit.error}</pre>

          {kit.hint && (
            <>
              <p className="font-bold mt-3">Hint:</p>
              <pre className="whitespace-pre-wrap">{kit.hint}</pre>
            </>
          )}

          {kit.raw && (
            <>
              <p className="font-bold mt-3">Raw Output:</p>
              <pre className="whitespace-pre-wrap">{kit.raw}</pre>
            </>
          )}

          {kit.fixed && (
            <>
              <p className="font-bold mt-3">Fixed Output:</p>
              <pre className="whitespace-pre-wrap">{kit.fixed}</pre>
            </>
          )}
        </div>
      )}

      {/* Render kit */}
      {kit && !kit.error && (
        <div className="space-y-6">

          <section className="p-4 border rounded">
            <h2 className="font-bold mb-2">Hooks</h2>
            <ul className="list-disc pl-6">
              {hooks.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          </section>

          <section className="p-4 border rounded">
            <h2 className="font-bold mb-2">Titles</h2>
            <ul className="list-disc pl-6">
              {titles.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          </section>

          <section className="p-4 border rounded">
            <h2 className="font-bold mb-2">Description</h2>
            <p>{description || "-"}</p>
          </section>

          <section className="p-4 border rounded">
            <h2 className="font-bold mb-2">Tags</h2>
            <p>{tags.length ? tags.join(", ") : "-"}</p>
          </section>

          <section className="p-4 border rounded">
            <h2 className="font-bold mb-2">Thumbnail</h2>
            <p><b>Text:</b> {thumbnail.text || "-"}</p>
            <p className="mt-2"><b>Prompt:</b> {thumbnail.prompt || "-"}</p>
          </section>

          <section className="p-4 border rounded">
            <h2 className="font-bold mb-2">Shorts</h2>
            {shorts.length === 0 ? (
              <p>-</p>
            ) : (
              <div className="space-y-4">
                {shorts.map((s, i) => (
                  <div key={i} className="border rounded p-3">
                    <p className="font-semibold">{s.title}</p>
                    <pre className="whitespace-pre-wrap mt-2">{s.script}</pre>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="p-4 border rounded">
            <h2 className="font-bold mb-2">Script</h2>
            <pre className="whitespace-pre-wrap">{script || "-"}</pre>
          </section>

        </div>
      )}
    </main>
  );
}