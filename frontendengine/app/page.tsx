"use client";

import { useState } from "react";
import axios from "axios";

export default function Home() {
  const [message, setMessage] = useState("");

  const checkBackend = async () => {
    try {
      const res = await axios.get("http://127.0.0.1:8000/api/health/");
      setMessage(res.data.status);
    } catch (err) {
      setMessage("Backend not reachable");
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6">
      <h1 className="text-3xl font-bold">Creative Production Engine</h1>
      <button
        onClick={checkBackend}
        className="px-4 py-2 bg-black text-white rounded"
      >
        Test Backend
      </button>
      <p>{message}</p>
    </main>
  );
}