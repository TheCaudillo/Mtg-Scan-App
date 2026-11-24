"""Mode A: OpenCLIP art embeddings + FAISS cosine index (language-agnostic artwork match).

Index files (data/art_index/):
  index.faiss        IndexFlatIP over L2-normalised embeddings
  ids.json           [{"illustration_id", "card_id"}] aligned with index rows
  shards/*.npz       resumable embedding shards written by scripts/build_art_index.py
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import get_settings
from .base import VisualHit, VisualIndex

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


class ClipEmbedder:
    _lock = threading.Lock()
    _instance: Optional["ClipEmbedder"] = None

    def __init__(self, model_name: str, pretrained: str):
        import open_clip
        import torch

        torch.set_num_threads(max(1, (os.cpu_count() or 2)))
        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
        self.model.eval()

    @classmethod
    def get(cls) -> "ClipEmbedder":
        with cls._lock:
            if cls._instance is None:
                s = get_settings()
                cls._instance = cls(s.clip_model, s.clip_pretrained)
            return cls._instance

    def embed_bgr(self, images: list[np.ndarray]) -> np.ndarray:
        from PIL import Image
        pil = [Image.fromarray(img[:, :, ::-1]) for img in images]
        return self.embed_pil(pil)

    def embed_pil(self, images) -> np.ndarray:
        torch = self.torch
        with torch.no_grad():
            batch = torch.stack([self.preprocess(im.convert("RGB")) for im in images])
            feats = self.model.encode_image(batch).float()
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().astype(np.float32)


class ClipFaissIndex(VisualIndex):
    name = "clip"

    def __init__(self, index_dir: Path | None = None):
        import faiss

        d = index_dir or get_settings().index_dir
        self.index = faiss.read_index(str(d / "index.faiss"))
        self.ids: list[dict] = json.loads((d / "ids.json").read_text())
        self.embedder = ClipEmbedder.get()

    @staticmethod
    def available(index_dir: Path | None = None) -> bool:
        d = index_dir or get_settings().index_dir
        if not (d / "index.faiss").exists():
            return False
        try:
            import faiss  # noqa: F401
            import open_clip  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def size(self) -> int:
        return self.index.ntotal

    def search(self, art_crops: list[np.ndarray], k: int = 8) -> list[list[VisualHit]]:
        if not art_crops:
            return []
        q = self.embedder.embed_bgr(art_crops)
        scores, idx = self.index.search(q, k)
        out = []
        for srow, irow in zip(scores, idx):
            hits = []
            for s, i in zip(srow, irow):
                if i < 0:
                    continue
                meta = self.ids[i]
                hits.append(VisualHit(meta["illustration_id"], meta["card_id"], float(s)))
            out.append(hits)
        return out
