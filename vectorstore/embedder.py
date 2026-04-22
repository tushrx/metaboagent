"""
PubMedBERT embedding pipeline (CPU-only).

Runs on CPU to keep all 4 L40 GPUs free for Gemma 4 vLLM. Uses mean-pooling
over the last hidden state (standard for PubMedBERT embeddings).

Usage
    from vectorstore.embedder import Embedder
    emb = Embedder()
    vectors = emb.embed(["text one", "text two"])   # -> np.ndarray (2, 768)
"""
from __future__ import annotations

import logging
from typing import Iterable

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from config import EMBEDDING_BATCH_SIZE, EMBEDDING_DEVICE, EMBEDDING_MODEL_NAME

log = logging.getLogger(__name__)


class Embedder:
    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL_NAME,
        device: str = EMBEDDING_DEVICE,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        max_length: int = 512,
    ):
        log.info("Loading embedding model %s on %s", model_name, device)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(device)
        self.model.eval()
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length

    @torch.no_grad()
    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.model.config.hidden_size), dtype=np.float32)
        out: list[np.ndarray] = []
        for i in range(0, len(texts), self.batch_size):
            batch = [t if t else " " for t in texts[i : i + self.batch_size]]
            enc = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            ).to(self.device)
            hidden = self.model(**enc).last_hidden_state  # (B, T, H)
            mask = enc["attention_mask"].unsqueeze(-1).float()
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            out.append(pooled.cpu().numpy().astype(np.float32))
        return np.vstack(out)

    def embed_iter(self, texts: Iterable[str]):
        """Yield embeddings batch-by-batch to keep memory flat for large corpora."""
        buf: list[str] = []
        for t in texts:
            buf.append(t)
            if len(buf) >= self.batch_size:
                yield self.embed(buf)
                buf = []
        if buf:
            yield self.embed(buf)
