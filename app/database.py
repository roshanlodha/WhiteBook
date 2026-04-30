from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


DB_PATH = "/data/staffbook_kb.sqlite"
EMBED_MODEL_NAME = "Alibaba-NLP/gte-modernbert-base"


@dataclass(frozen=True, slots=True)
class ChunkRecord:
	id: str
	heading_context: str | None
	text_content: str
	page_start: int | None
	page_end: int | None
	image_filename: str | None


class VectorStore:
	def __init__(self, db_path: str | os.PathLike[str] | None = None) -> None:
		self.db_path = Path(db_path) if db_path is not None else Path(DB_PATH)
		if not self.db_path.exists():
			raise FileNotFoundError(f"Database not found at {self.db_path}")

		from sentence_transformers import SentenceTransformer

		self.embedder = SentenceTransformer(EMBED_MODEL_NAME, trust_remote_code=True)
		self._records: list[ChunkRecord] = []
		self._embeddings: np.ndarray | None = None
		self._embedding_norms: np.ndarray | None = None
		self._load_all_rows()

	def _load_all_rows(self) -> None:
		with sqlite3.connect(self.db_path) as conn:
			cursor = conn.cursor()
			cursor.execute(
				"""
				SELECT id, heading_context, text_content, page_start, page_end, image_filename, embedding
				FROM chunks
				ORDER BY rowid
				"""
			)
			rows: list[tuple[Any, ...]] = cursor.fetchall()

		if not rows:
			self._records = []
			self._embeddings = np.empty((0, 0), dtype=np.float32)
			self._embedding_norms = np.empty((0,), dtype=np.float32)
			return

		records: list[ChunkRecord] = []
		embeddings: list[np.ndarray] = []

		for row in rows:
			chunk_id, heading_context, text_content, page_start, page_end, image_filename, embedding_blob = row
			if embedding_blob is None:
				continue

			vector = np.frombuffer(embedding_blob, dtype=np.float32).astype(np.float32, copy=False)
			records.append(
				ChunkRecord(
					id=str(chunk_id),
					heading_context=str(heading_context) if heading_context is not None else None,
					text_content=str(text_content),
					page_start=int(page_start) if page_start is not None else None,
					page_end=int(page_end) if page_end is not None else None,
					image_filename=str(image_filename) if image_filename is not None else None,
				)
			)
			embeddings.append(vector)

		if not embeddings:
			self._records = []
			self._embeddings = np.empty((0, 0), dtype=np.float32)
			self._embedding_norms = np.empty((0,), dtype=np.float32)
			return

		embedding_matrix = np.vstack(embeddings).astype(np.float32, copy=False)
		self._records = records
		self._embeddings = embedding_matrix
		self._embedding_norms = np.linalg.norm(embedding_matrix, axis=1)

	@property
	def size(self) -> int:
		return len(self._records)

	def search(self, query: str, top_k: int = 5, cutoff: float = 0.6) -> list[dict[str, Any]]:
		if not query.strip() or self._embeddings is None or self._embeddings.size == 0:
			return []

		query_vector = self.embedder.encode(query).astype(np.float32, copy=False)
		query_norm = float(np.linalg.norm(query_vector))
		if query_norm == 0.0:
			return []

		denominator = self._embedding_norms * query_norm
		valid_mask = denominator > 0
		if not np.any(valid_mask):
			return []

		scores = np.zeros(len(self._records), dtype=np.float32)
		scores[valid_mask] = (self._embeddings[valid_mask] @ query_vector) / denominator[valid_mask]

		ranked_indices = [int(index) for index in np.argsort(scores)[::-1] if scores[index] >= cutoff]
		ranked_indices = ranked_indices[:top_k]

		results: list[dict[str, Any]] = []
		for index in ranked_indices:
			record = self._records[index]
			results.append(
				{
					"id": record.id,
					"heading_context": record.heading_context,
					"text_content": record.text_content,
					"page_start": record.page_start,
					"page_end": record.page_end,
					"image_filename": record.image_filename,
					"score": float(scores[index]),
				}
			)

		return results
