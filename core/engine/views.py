"""
Creative Production Engine (Hackathon Backend)
==============================================

What this backend does:
- Generates a "content kit" from a single topic using a local LLM (Ollama)
- Ensures the output is STRICT JSON (even if the model returns broken JSON)
- Supports per-section regeneration (hooks/titles/description/tags/thumbnail/shorts/script)
- Stores last N kits in DB for demo/history
- Exports a kit into a plain-text "ready to use" bundle

Hackathon Value:
- Reliability layer: LLMs often return invalid JSON (quotes, newlines, timestamps).
  This backend includes a progressive JSON repair pipeline so your MVP stays functional.
"""

import json
import re
import ast
import requests
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import HttpResponse

from .models import ProductionKit


# -------------------------
# Helpers (Data Structure)
# -------------------------

def empty_kit(topic: str, tone: str = "cinematic", language: str = "English"):
    """
    Returns a clean kit template.
    Used when:
    - User didn't provide topic (validation error)
    - Model fails / returns invalid output
    - We need a consistent response shape for frontend UI
    """
    return {
        "topic": topic,
        "tone": tone,
        "language": language,
        "hooks": [],
        "titles": [],
        "description": "",
        "tags": [],
        "thumbnail": {"text": "", "prompt": ""},
        "shorts": [],
        "script": "",
    }


# -------------------------
# JSON Repair Layer (Critical)
# -------------------------

def repair_json(raw: str) -> str:
    """
    Repairs common LLM JSON issues:
    - LLM adds explanation text before JSON (e.g. "Here is your JSON:")
    - Missing closing braces/brackets
    - Trailing garbage after the JSON object

    This is the first defensive layer.
    """
    if not raw:
        return raw

    start = raw.find("{")
    if start == -1:
        return raw

    raw = raw[start:].strip()

    # Balance square brackets [] if model forgot to close them
    open_sq = raw.count("[")
    close_sq = raw.count("]")
    if close_sq < open_sq:
        raw += "]" * (open_sq - close_sq)

    # Balance curly braces {} if model forgot to close them
    open_c = raw.count("{")
    close_c = raw.count("}")
    if close_c < open_c:
        raw += "}" * (open_c - close_c)

    # Trim anything after the final closing brace
    last = raw.rfind("}")
    if last != -1:
        raw = raw[: last + 1]

    return raw


# 1) Fix time tokens: 7:30 -> "7:30"
#    Why: JSON expects strings, but LLM sometimes outputs 7:30 as a bare token (invalid JSON).
_TIME_TOKEN_RE = re.compile(r'(:\s*)(\d{1,2}:\d{2})(\s*[,}\]])')

def repair_json_times(raw: str) -> str:
    """
    Converts invalid time tokens into valid JSON strings:
    Example:
      "duration": 7:30 -> "duration": "7:30"
      "time": 2:15,    -> "time": "2:15",
    """
    if not raw:
        return raw

    def repl(m: re.Match) -> str:
        return f'{m.group(1)}"{m.group(2)}"{m.group(3)}'

    return _TIME_TOKEN_RE.sub(repl, raw)


# 2) Fix single-quoted strings in lists (titles/tags) while preserving dynasty's
#    Why: LLM sometimes emits Python-style strings: ['a', 'b'] instead of JSON ["a","b"]
_SINGLE_QUOTED_STRING_RE = re.compile(r"'((?:[^'\\]|\\.|(?<=\w)'(?=\w))*)'")

def fix_single_quotes_in_list(raw: str) -> str:
    """
    Converts single-quoted strings into JSON-safe double-quoted strings.
    Handles contractions/possessives like "dynasty's" properly.
    """
    if not raw:
        return raw

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        inner = inner.replace('\\"', '"')   # unescape \" if present
        inner = inner.replace('"', '\\"')   # escape " for JSON safety
        return f'"{inner}"'

    return _SINGLE_QUOTED_STRING_RE.sub(repl, raw)


# 3) Fix multiline value string corruption (description/script often break JSON)
#    Why: JSON strings cannot contain raw newline characters; they must be escaped as \n.
_VALUE_STRING_RE = re.compile(r'("value"\s*:\s*)"(.*?)"\s*(?=\}\s*$)', re.DOTALL)

def repair_multiline_value_string(raw: str) -> str:
    """
    Repairs this common issue:
      "value": "
        line1
        line2
      "

    We re-encode the inner content via json.dumps so:
    - new lines become \\n
    - quotes become escaped safely
    """
    if not raw:
        return raw

    def repl(m: re.Match) -> str:
        prefix = m.group(1)
        inner = m.group(2)
        safe = json.dumps(inner)  # returns JSON string including surrounding quotes
        return prefix + safe

    return _VALUE_STRING_RE.sub(repl, raw)


def try_literal_eval_object(raw: str):
    """
    Last-resort parse:
    If model outputs Python-literal dict/list (not JSON),
    ast.literal_eval may successfully parse it.

    This is used only after JSON repair attempts fail.
    """
    if not raw:
        return None

    s = repair_json(raw)
    try:
        return ast.literal_eval(s)
    except Exception:
        return None


def extract_first_json_object(raw: str) -> str:
    """
    Extracts the first complete JSON object from raw model output.

    Why this matters:
    Models sometimes output:
      "Here is your JSON:\n{...}\nThanks!"

    This function finds the first '{' and returns the fully balanced object,
    while respecting quoted strings so braces inside strings don't break parsing.
    """
    if not raw:
        return raw

    start = raw.find("{")
    if start == -1:
        return raw

    s = raw[start:]
    depth = 0
    in_str = False
    esc = False

    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[: i + 1]

    # If never balanced, return trimmed tail (repair_json() handles balancing)
    return s


def safe_json_loads(raw: str):
    """
    Progressive JSON parse strategy (robustness pipeline):
    1) Extract first JSON object (removes junk before/after)
    2) Try json.loads directly
    3) Try repair_json (balance braces etc)
    4) Try repair_json_times (quote 7:30)
    5) Try fix_single_quotes_in_list (convert 'abc' -> "abc")
    6) Try repair_multiline_value_string (escape newlines/quotes properly)
    7) Last resort: ast.literal_eval for python-literal responses

    Returns:
      parsed_obj, fixed_string_used, error_message_or_None
    """
    if not raw:
        return None, raw, "Empty response"

    raw0 = extract_first_json_object(raw)

    # 1) Try direct JSON
    try:
        return json.loads(raw0), raw0, None
    except Exception:
        pass

    # 2) minimal repairs
    fixed1 = repair_json(raw0)
    try:
        return json.loads(fixed1), fixed1, None
    except Exception:
        pass

    # 3) time repair
    fixed2 = repair_json_times(fixed1)
    try:
        return json.loads(fixed2), fixed2, None
    except Exception:
        pass

    # 4) single-quote repair
    fixed3 = fix_single_quotes_in_list(fixed2)
    try:
        return json.loads(fixed3), fixed3, None
    except Exception:
        pass

    # 5) multiline repair
    fixed4 = repair_multiline_value_string(fixed3)
    try:
        return json.loads(fixed4), fixed4, None
    except Exception as e:
        # 6) literal eval fallback
        obj = try_literal_eval_object(raw0)
        if obj is not None:
            return obj, fixed4, None
        return None, fixed4, str(e)


# -------------------------
# Ollama Model Caller
# -------------------------

def call_ollama(prompt: str, model: str = "llama3") -> str:
    """
    Calls local Ollama generation endpoint.

    Hackathon stability choices:
    - format="json": asks Ollama to enforce JSON output formatting
    - temperature=0.2: lower randomness = fewer broken JSON outputs
    """
    r = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",               # force JSON mode when supported
            "options": {"temperature": 0.2} # stable structured outputs
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("response", "")


# -------------------------
# APIs
# -------------------------

@api_view(["GET"])
def health_check(request):
    """
    Quick health endpoint for:
    - local testing
    - demo readiness
    - frontend "backend is alive" check
    """
    return Response({"status": "Backend is running"})


@api_view(["POST"])
def generate_kit(request):
    """
    Generates a full production kit from a topic.
    Output includes:
      hooks, titles, description, tags, thumbnail prompt, shorts scripts, long script

    This is your main MVP endpoint for demo.
    """
    topic = (request.data.get("topic") or "").strip()
    tone = (request.data.get("tone") or "cinematic").strip()
    language = (request.data.get("language") or "English").strip()

    kit = empty_kit(topic, tone, language)

    # Input validation: always return safe kit shape
    if not topic:
        kit["error"] = "Topic is required"
        return Response(kit, status=400)

    prompt = f"""
You are a Creative Production Engine.

Return ONLY valid JSON.
Do NOT wrap in markdown.
End your response with the final closing brace }} and nothing after it.

IMPORTANT JSON RULES:
- Use ONLY double quotes for all strings.
- Any time values MUST be strings, e.g. "7:30" not 7:30.
- For multiline text (description/script) use \\n, do NOT place raw newlines inside the JSON string.

Schema:
{{
  "topic": "string",
  "tone": "string",
  "language": "string",
  "hooks": ["string","string","string","string","string"],
  "titles": ["string","string","string","string","string"],
  "description": "string",
  "tags": ["string","string","string","string","string","string","string","string","string","string"],
  "thumbnail": {{ "text": "string", "prompt": "string" }},
  "shorts": [
    {{ "title":"string", "script":"string" }},
    {{ "title":"string", "script":"string" }},
    {{ "title":"string", "script":"string" }},
    {{ "title":"string", "script":"string" }},
    {{ "title":"string", "script":"string" }}
  ],
  "script": "string"
}}

Rules:
- hooks = 5 (full sentences, curiosity hooks)
- titles = 5 (high CTR)
- tags = 10
- shorts = 5 (25–45 sec scripts, hook first line)
- script = 6–8 min voiceover (structured)
- thumbnail.text <= 30 characters

Topic: {topic}
Tone: {tone}
Language: {language}
"""

    try:
        raw = call_ollama(prompt)

        # Robust JSON extraction + repair
        parsed, fixed_used, err = safe_json_loads(raw)
        if parsed is None:
            kit["error"] = "Model did not return valid JSON (even after repair)"
            kit["raw"] = raw
            kit["fixed"] = fixed_used
            kit["hint"] = f"JSON parse error: {err}"
            return Response(kit, status=200)

        # Merge parsed output into kit structure
        kit.update({
            "topic": parsed.get("topic", topic),
            "tone": parsed.get("tone", tone),
            "language": parsed.get("language", language),
            "hooks": parsed.get("hooks", []) or [],
            "titles": parsed.get("titles", []) or [],
            "description": parsed.get("description", "") or "",
            "tags": parsed.get("tags", []) or [],
            "thumbnail": parsed.get("thumbnail", {"text": "", "prompt": ""}) or {"text": "", "prompt": ""},
            "shorts": parsed.get("shorts", []) or [],
            "script": parsed.get("script", "") or "",
        })

        # Type safety: prevent frontend crashes if model returns wrong types
        if not isinstance(kit["hooks"], list): kit["hooks"] = []
        if not isinstance(kit["titles"], list): kit["titles"] = []
        if not isinstance(kit["tags"], list): kit["tags"] = []
        if not isinstance(kit["shorts"], list): kit["shorts"] = []
        if not isinstance(kit["thumbnail"], dict): kit["thumbnail"] = {"text": "", "prompt": ""}

        # Persist the successful kit for history sidebar
        try:
            ProductionKit.objects.create(
                topic=kit.get("topic", topic),
                tone=kit.get("tone", tone),
                language=kit.get("language", language),
                kit=kit
            )
            # Keep only last 5 kits for a clean demo
            ids_to_keep = list(ProductionKit.objects.values_list("id", flat=True)[:5])
            ProductionKit.objects.exclude(id__in=ids_to_keep).delete()
        except Exception:
            # never break response due to DB issues (hackathon robustness)
            pass

        return Response(kit, status=200)

    except requests.exceptions.ConnectionError:
        kit["error"] = "Cannot connect to Ollama. Is it running?"
        kit["hint"] = "Run: ollama serve (or open Ollama app) and then: ollama run llama3"
        return Response(kit, status=200)

    except requests.exceptions.Timeout:
        kit["error"] = "Ollama request timed out."
        return Response(kit, status=200)

    except Exception as e:
        kit["error"] = f"Server error: {str(e)}"
        return Response(kit, status=500)


@api_view(["POST"])
def regenerate_section(request):
    """
    Regenerates ONE section of an existing kit.

    Why this matters:
    - Creator can iterate quickly (titles too weak? regenerate only titles)
    - Faster than generating entire kit again
    - Great demo feature for hackathon judges

    Request:
      { "section": "titles", "kit": {...} }

    Response:
      { "section": "titles", "value": [...] }
    """
    section = (request.data.get("section") or "").strip()
    kit = request.data.get("kit") or {}

    allowed = {"hooks", "titles", "shorts", "thumbnail", "script", "description", "tags"}
    if section not in allowed:
        return Response({"error": "Invalid section"}, status=400)

    topic = (kit.get("topic") or "").strip()
    tone = (kit.get("tone") or "cinematic").strip()
    language = (kit.get("language") or "English").strip()

    if not topic:
        return Response({"error": "Missing kit.topic"}, status=400)

    # Per-section instructions (keeps output consistent)
    rules = {
        "hooks": "Generate 5 curiosity hooks. Each hook must be a full punchy sentence.",
        "titles": "Generate 5 high-CTR YouTube titles. Curiosity + clarity, not spam.",
        "shorts": "Generate 5 shorts. Each: title + 25-45 sec script. Hook in first line.",
        "thumbnail": "Generate thumbnail object with text<=30 chars + cinematic image prompt.",
        "script": "Generate a 6-8 min structured voiceover script (hook, buildup, payoff, CTA). If you use timestamps like 2:15, they MUST be strings like \"2:15\". For multiline text, use \\n.",
        "description": "Generate SEO-friendly YouTube description (2 paragraphs + CTA). Return as ONE JSON string using \\n for new lines.",
        "tags": "Generate 10 tags as JSON array of 10 strings.",
    }[section]

    prompt = f"""
You are regenerating ONE section of an existing production kit.

Return ONLY valid JSON.
End with }} and nothing after it.

IMPORTANT JSON RULES:
- Use ONLY double quotes for all strings.
- Any time values MUST be strings, e.g. "7:30" not 7:30.
- For multiline text use \\n, do NOT put raw newlines inside the JSON string.

Topic: {topic}
Tone: {tone}
Language: {language}

Keep consistent with existing kit:
Existing hooks: {kit.get("hooks", [])}
Existing titles: {kit.get("titles", [])}

Task: {rules}

Return JSON EXACTLY:
{{
  "section": "{section}",
  "value": <value>
}}
"""

    try:
        raw = call_ollama(prompt)

        parsed, fixed_used, err = safe_json_loads(raw)
        if parsed is None:
            # Return debug info so you can show "resilience layer" in demo
            return Response(
                {"error": "Invalid JSON from model", "raw": raw, "fixed": fixed_used, "hint": err},
                status=200
            )

        if "section" not in parsed or "value" not in parsed:
            return Response(
                {"error": "Model response missing section/value", "raw": raw, "fixed": fixed_used},
                status=200
            )

        return Response(parsed, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["POST"])
def export_kit(request):
    """
    Exports the current kit into a plain-text bundle.
    Hackathon demo benefit:
    - shows end-to-end utility
    - "ready to publish" output
    """
    data = request.data
    topic = data.get("topic", "Untitled")

    def lines(title):
        return f"\n\n====================\n{title}\n====================\n"

    content = ""
    content += lines("CREATIVE PRODUCTION KIT")
    content += f"TOPIC: {topic}\n"
    content += f"TONE: {data.get('tone','')}\n"
    content += f"LANGUAGE: {data.get('language','')}\n"

    content += lines("HOOKS")
    for h in data.get("hooks", []):
        content += f"- {h}\n"

    content += lines("TITLES")
    for t in data.get("titles", []):
        content += f"- {t}\n"

    content += lines("DESCRIPTION")
    content += f"{data.get('description','')}\n"

    content += lines("TAGS")
    tags = data.get("tags", [])
    content += ", ".join(tags) + "\n"

    thumb = data.get("thumbnail", {}) or {}
    content += lines("THUMBNAIL")
    content += f"Text: {thumb.get('text','')}\n"
    content += f"Prompt: {thumb.get('prompt','')}\n"

    content += lines("SHORTS")
    for s in data.get("shorts", []):
        content += f"\nTitle: {s.get('title','')}\n"
        content += f"Script: {s.get('script','')}\n"

    content += lines("LONG SCRIPT")
    content += f"{data.get('script','')}\n"

    resp = HttpResponse(content, content_type="text/plain")
    safe = "".join(c for c in topic[:30] if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
    resp["Content-Disposition"] = f'attachment; filename="{safe}_kit.txt"'
    return resp


@api_view(["GET"])
def recent_kits(request):
    """
    Returns recent kits for sidebar history.
    Helps demo:
    - persistence
    - iteration workflow
    """
    limit = int(request.query_params.get("limit", 5))
    limit = max(1, min(limit, 20))

    kits = ProductionKit.objects.all()[:limit]

    data = [
        {
            "id": k.id,
            "topic": k.topic,
            "tone": k.tone,
            "language": k.language,
            "created_at": k.created_at.isoformat(),
        }
        for k in kits
    ]
    return Response({"results": data})


@api_view(["GET"])
def kit_detail(request, kit_id: int):
    """
    Loads a kit by ID from DB.
    Used by frontend when user clicks a history item.
    """
    try:
        k = ProductionKit.objects.get(id=kit_id)
    except ProductionKit.DoesNotExist:
        return Response({"error": "Kit not found"}, status=404)

    return Response({
        "id": k.id,
        "topic": k.topic,
        "tone": k.tone,
        "language": k.language,
        "created_at": k.created_at.isoformat(),
        "kit": k.kit,
    })