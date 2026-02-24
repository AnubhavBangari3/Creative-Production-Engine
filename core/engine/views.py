import json
import requests
from rest_framework.decorators import api_view
from rest_framework.response import Response


def empty_kit(topic: str, tone: str = "cinematic", language: str = "English"):
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


def repair_json(raw: str) -> str:
    """
    Repairs common LLM JSON issues:
    - text before JSON
    - missing closing braces/brackets
    - trailing garbage
    """
    if not raw:
        return raw

    start = raw.find("{")
    if start == -1:
        return raw
    raw = raw[start:].strip()

    # balance square brackets
    open_sq = raw.count("[")
    close_sq = raw.count("]")
    if close_sq < open_sq:
        raw += "]" * (open_sq - close_sq)

    # balance curly braces
    open_c = raw.count("{")
    close_c = raw.count("}")
    if close_c < open_c:
        raw += "}" * (open_c - close_c)

    # trim after last }
    last = raw.rfind("}")
    if last != -1:
        raw = raw[: last + 1]
    return raw


def call_ollama(prompt: str, model: str = "llama3") -> str:
    r = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7},
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("response", "")


@api_view(["GET"])
def health_check(request):
    return Response({"status": "Backend is running"})


@api_view(["POST"])
def generate_kit(request):
    topic = (request.data.get("topic") or "").strip()
    tone = (request.data.get("tone") or "cinematic").strip()
    language = (request.data.get("language") or "English").strip()

    kit = empty_kit(topic, tone, language)

    if not topic:
        kit["error"] = "Topic is required"
        return Response(kit, status=400)

    prompt = f"""
You are a Creative Production Engine.

Return ONLY valid JSON.
Do NOT wrap in markdown.
End your response with the final closing brace }} and nothing after it.

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
    # Auto-save successful generations
    try:
        ProductionKit.objects.create(
            topic=kit.get("topic", topic),
            tone=kit.get("tone", tone),
            language=kit.get("language", language),
            kit=kit
        )

        # keep only last 5 in DB (hackathon style)
        ids_to_keep = list(ProductionKit.objects.values_list("id", flat=True)[:5])
        ProductionKit.objects.exclude(id__in=ids_to_keep).delete()
    except Exception:
        pass

    try:
        raw = call_ollama(prompt)
        fixed = repair_json(raw)

        try:
            parsed = json.loads(fixed)
        except Exception:
            kit["error"] = "Model did not return valid JSON (even after repair)"
            kit["raw"] = raw
            kit["fixed"] = fixed
            return Response(kit, status=200)

        # merge safely
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

        # hard safety
        if not isinstance(kit["hooks"], list): kit["hooks"] = []
        if not isinstance(kit["titles"], list): kit["titles"] = []
        if not isinstance(kit["tags"], list): kit["tags"] = []
        if not isinstance(kit["shorts"], list): kit["shorts"] = []
        if not isinstance(kit["thumbnail"], dict): kit["thumbnail"] = {"text": "", "prompt": ""}

        return Response(kit, status=200)

    except requests.exceptions.ConnectionError:
        kit["error"] = "Cannot connect to Ollama. Is it running?"
        kit["hint"] = "Run: ollama serve  (or open Ollama app) and then: ollama run llama3"
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
    Input:
    {
      "section": "hooks|titles|shorts|thumbnail|script|description|tags",
      "kit": { ...existing kit json... }
    }
    Output:
    { "section": "...", "value": <new section value> }
    """
    section = (request.data.get("section") or "").strip()
    kit = request.data.get("kit") or {}

    allowed = {"hooks","titles","shorts","thumbnail","script","description","tags"}
    if section not in allowed:
        return Response({"error": "Invalid section"}, status=400)

    topic = (kit.get("topic") or "").strip()
    tone = (kit.get("tone") or "cinematic").strip()
    language = (kit.get("language") or "English").strip()

    if not topic:
        return Response({"error": "Missing kit.topic"}, status=400)

    rules = {
        "hooks": "Generate 5 curiosity hooks. Each hook must be a full punchy sentence.",
        "titles": "Generate 5 high-CTR YouTube titles. Curiosity + clarity, not spam.",
        "shorts": "Generate 5 shorts. Each: title + 25-45 sec script. Hook in first line.",
        "thumbnail": "Generate thumbnail object with text<=30 chars + cinematic image prompt.",
        "script": "Generate a 6-8 min structured voiceover script (hook, buildup, payoff, CTA).",
        "description": "Generate SEO-friendly YouTube description (2 paragraphs + CTA).",
        "tags": "Generate 10 tags as JSON array of 10 strings.",
    }[section]

    prompt = f"""
You are regenerating ONE section of an existing production kit.

Return ONLY valid JSON.
End with }} and nothing after it.

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
        fixed = repair_json(raw)

        try:
            parsed = json.loads(fixed)
        except Exception:
            return Response({"error": "Invalid JSON from model", "raw": raw, "fixed": fixed}, status=200)

        # Ensure exact keys exist
        if "section" not in parsed or "value" not in parsed:
            return Response({"error": "Model response missing section/value", "raw": raw, "fixed": fixed}, status=200)

        return Response(parsed, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)
    
from django.http import HttpResponse

@api_view(["POST"])
def export_kit(request):
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

from .models import ProductionKit

@api_view(["GET"])
def recent_kits(request):
    limit = int(request.query_params.get("limit", 5))
    limit = max(1, min(limit, 20))  # safety
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