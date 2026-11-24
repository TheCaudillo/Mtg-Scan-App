"""Mode B: fast vision-LLM reader + targeted disambiguator (Anthropic / OpenAI / Gemini).

Plain HTTP via httpx (no vendor SDKs). Output is strict JSON parsed into `VisionRead`; nothing
it returns is trusted until resolver.py validates it against scryfall.db.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Any, Optional

import cv2
import httpx
import numpy as np

from ..config import Settings, get_settings
from ..detect.base import CardCrops
from ..models import Printing, VisionRead
from .base import FieldReader

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-2.5-flash",
}

ALLOWED_ENUMS = {
    "foil_symbol": {"dot", "star", "none", "unclear"},
    "foil_sheen": {"clear", "none", "unclear"},
    "border": {"black", "white", "borderless", "silver", "gold", "unclear"},
}

READ_PROMPT = """You are reading ONE physical Magic: The Gathering card from a phone photo.
Image 1: the whole card (deskewed). Image 2: zoomed bottom-left collector strip.
Return ONLY a JSON object with these keys (use null when you cannot read something; never guess numbers):
{
 "name": English card name if you know it, else null,
 "printed_name": the name exactly as printed on the card (may be Spanish etc.),
 "language": two-letter code of the printed language (en, es, fr, de, it, pt, ja, ko, ru, zhs, zht),
 "set_code": set code from the strip (e.g. "MID"), or null,
 "collector_number": collector number from the strip without the "/total" part (e.g. "10"), or null,
 "rarity_letter": one of C U R M S P L T or null,
 "foil_symbol": "dot" if the strip shows • between set and language, "star" if ★, "none" if old card without it, "unclear",
 "foil_sheen": "clear" if obvious rainbow foil sheen, "none" if clearly matte, "unclear",
 "border": "black" | "white" | "borderless" | "silver" | "gold" | "unclear",
 "frame_cues": list from ["extended_art","borderless","showcase","retro_frame","full_art","etched","secret_lair","serialized"],
 "text_snippet": first 8 words of the rules text as printed,
 "is_card": false if this is an empty sleeve, a card back or not a card,
 "confidence": 0..1 confidence in the name
}"""

CHOOSE_PROMPT = """These are photos of ONE physical Magic card (whole card, zoomed collector strip, zoomed set symbol).
It is one of the printings listed below. Use the set code / collector number in the strip, the set
symbol, frame/border style and rules wording to decide. Answer ONLY JSON:
{{"index": <0-based index of the matching printing or null if you cannot tell>, "reason": "<short>"}}
Printings:
{options}"""


def _b64jpeg(img: np.ndarray, max_side: int = 768, quality: int = 85) -> str:
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s < 1:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


class VisionLLMReader(FieldReader):
    name = "vision"

    def __init__(self, settings: Settings | None = None):
        s = settings or get_settings()
        self.provider = s.vision_provider
        self.model = s.vision_model or DEFAULT_MODELS.get(self.provider, "")
        self.key = {"anthropic": s.anthropic_api_key, "openai": s.openai_api_key, "gemini": s.gemini_api_key}.get(self.provider, "")
        if self.provider not in DEFAULT_MODELS:
            raise ValueError(f"VISION_PROVIDER must be one of {list(DEFAULT_MODELS)}")
        if not self.key:
            raise ValueError(f"missing API key for VISION_PROVIDER={self.provider}")
        self.sem = asyncio.Semaphore(max(1, s.vision_concurrency))
        self.timeout = s.vision_timeout_s
        self.name = f"vision:{self.provider}"

    @staticmethod
    def configured(settings: Settings | None = None) -> bool:
        s = settings or get_settings()
        key = {"anthropic": s.anthropic_api_key, "openai": s.openai_api_key, "gemini": s.gemini_api_key}.get(s.vision_provider)
        return bool(s.vision_provider and key)

    # ---- provider calls ---------------------------------------------------------------------
    async def _call(self, prompt: str, images: list[np.ndarray], max_tokens: int = 500) -> str:
        imgs = [_b64jpeg(i) for i in images]
        async with self.sem, httpx.AsyncClient(timeout=self.timeout) as c:
            if self.provider == "anthropic":
                content: list[dict[str, Any]] = [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}} for b in imgs
                ]
                content.append({"type": "text", "text": prompt})
                r = await c.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": self.model, "max_tokens": max_tokens, "temperature": 0,
                          "messages": [{"role": "user", "content": content}]},
                )
                r.raise_for_status()
                return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
            if self.provider == "openai":
                content = [{"type": "text", "text": prompt}] + [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}", "detail": "high"}} for b in imgs
                ]
                r = await c.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json={"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                          "response_format": {"type": "json_object"},
                          "messages": [{"role": "user", "content": content}]},
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            # gemini
            parts: list[dict[str, Any]] = [{"text": prompt}] + [
                {"inline_data": {"mime_type": "image/jpeg", "data": b}} for b in imgs
            ]
            r = await c.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.key},
                json={"contents": [{"parts": parts}],
                      "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}},
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    # ---- FieldReader --------------------------------------------------------------------------
    async def read(self, crops: CardCrops) -> Optional[VisionRead]:
        text = await self._call(READ_PROMPT, [crops.card, crops.strip])
        data = _extract_json(text)
        data = {k: v for k, v in data.items() if k in VisionRead.model_fields}
        for k, allowed in ALLOWED_ENUMS.items():
            if data.get(k) not in allowed:
                data[k] = None
        if isinstance(data.get("collector_number"), (int, float)):
            data["collector_number"] = str(int(data["collector_number"]))
        data["frame_cues"] = [str(x) for x in data.get("frame_cues") or []]
        read = VisionRead(**data, source=self.name)
        if read.set_code:
            read.set_code = read.set_code.lower()
        if read.language:
            read.language = read.language.lower()
        return read

    async def choose(self, crops: CardCrops, candidates: list[Printing]) -> Optional[int]:
        opts = "\n".join(
            f"{i}: {p.set_name} ({p.set_code.upper()}) #{p.collector_number}, released {p.released_at}, "
            f"border={p.border_color}, frame={p.frame}, effects={','.join(p.frame_effects) or '-'}, "
            f"treatments={','.join(p.treatments) or '-'}"
            for i, p in enumerate(candidates)
        )
        text = await self._call(CHOOSE_PROMPT.format(options=opts), [crops.card, crops.strip, crops.set_symbol], 200)
        idx = _extract_json(text).get("index")
        if isinstance(idx, int) and 0 <= idx < len(candidates):
            return idx
        return None
