"""ChromaDB vector store for chapter summaries and character states."""

from pathlib import Path
from typing import Optional

import chromadb


class ChromaStore:
    """Manages ChromaDB collections for novel memory."""

    CHAPTER_SUMMARIES = "chapter_summaries"
    CHARACTER_STATES = "character_states"
    WORLD_EVENTS = "world_events"

    def __init__(self, persist_dir: str | Path):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._init_collections()

    def _init_collections(self):
        """Initialize or get all required collections."""
        self.summaries = self.client.get_or_create_collection(
            name=self.CHAPTER_SUMMARIES,
            metadata={"hnsw:space": "cosine"},
        )
        self.characters = self.client.get_or_create_collection(
            name=self.CHARACTER_STATES,
            metadata={"hnsw:space": "cosine"},
        )
        self.events = self.client.get_or_create_collection(
            name=self.WORLD_EVENTS,
            metadata={"hnsw:space": "cosine"},
        )

    # ---- Chapter Summaries ----

    def add_chapter_summary(
        self,
        novel_id: int,
        chapter_number: int,
        summary: str,
        key_characters: str = "",
        key_events: str = "",
        emotional_tone: str = "",
    ):
        """Store a chapter summary with metadata."""
        doc_id = f"novel_{novel_id}_ch_{chapter_number}"
        metadata = {
            "novel_id": novel_id,
            "chapter_number": chapter_number,
            "key_characters": key_characters,
            "key_events": key_events,
            "emotional_tone": emotional_tone,
        }
        # Upsert to handle updates
        self.summaries.upsert(
            ids=[doc_id],
            documents=[summary],
            metadatas=[metadata],
        )

    def get_recent_summaries(
        self, novel_id: int, current_chapter: int, count: int = 3
    ) -> list[dict]:
        """Get the most recent chapter summaries by exact chapter number."""
        chapter_range = range(max(1, current_chapter - count), current_chapter)
        if not chapter_range:
            return []
        doc_ids = [f"novel_{novel_id}_ch_{ch}" for ch in chapter_range]
        try:
            result = self.summaries.get(ids=doc_ids, include=["documents", "metadatas"])
        except Exception:
            return []
        results = []
        if result["documents"]:
            for doc, meta in zip(result["documents"], result["metadatas"]):
                results.append({
                    "chapter_number": meta.get("chapter_number", 0),
                    "summary": doc,
                    "metadata": meta,
                })
        results.sort(key=lambda x: x["chapter_number"])
        return results

    def search_relevant_summaries(
        self,
        novel_id: int,
        query: str,
        exclude_chapters: Optional[list[int]] = None,
        top_k: int = 7,
    ) -> list[dict]:
        """Search for semantically relevant chapter summaries."""
        exclude_chapters = exclude_chapters or []

        # Query with novel_id filter
        results = self.summaries.query(
            query_texts=[query],
            n_results=top_k + len(exclude_chapters),
            where={"novel_id": novel_id},
            include=["documents", "metadatas", "distances"],
        )

        if not results["documents"] or not results["documents"][0]:
            return []

        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            ch_num = meta.get("chapter_number", 0)
            if ch_num not in exclude_chapters:
                output.append({
                    "chapter_number": ch_num,
                    "summary": doc,
                    "metadata": meta,
                    "distance": dist,
                })
            if len(output) >= top_k:
                break

        return output

    def get_all_summaries(self, novel_id: int) -> list[dict]:
        """Get all chapter summaries for a novel, ordered by chapter number."""
        results = self.summaries.get(
            where={"novel_id": novel_id},
            include=["documents", "metadatas"],
        )

        if not results["documents"]:
            return []

        items = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            items.append({
                "chapter_number": meta.get("chapter_number", 0),
                "summary": doc,
                "metadata": meta,
            })
        items.sort(key=lambda x: x["chapter_number"])
        return items

    # ---- Character States ----

    def add_character_state(
        self,
        novel_id: int,
        character_name: str,
        chapter_number: int,
        state_description: str,
    ):
        """Store a character's state at a given chapter."""
        doc_id = f"novel_{novel_id}_char_{character_name}_ch_{chapter_number}"
        metadata = {
            "novel_id": novel_id,
            "character_name": character_name,
            "chapter_number": chapter_number,
        }
        self.characters.upsert(
            ids=[doc_id],
            documents=[state_description],
            metadatas=[metadata],
        )

    def get_latest_character_state(
        self, novel_id: int, character_name: str
    ) -> Optional[dict]:
        """Get the most recent state for a character."""
        results = self.characters.get(
            where={
                "$and": [
                    {"novel_id": novel_id},
                    {"character_name": character_name},
                ]
            },
            include=["documents", "metadatas"],
        )

        if not results["documents"]:
            return None

        # Find the one with the highest chapter_number
        best = None
        best_ch = -1
        for doc, meta in zip(results["documents"], results["metadatas"]):
            ch = meta.get("chapter_number", 0)
            if ch > best_ch:
                best_ch = ch
                best = {
                    "character_name": character_name,
                    "chapter_number": ch,
                    "state": doc,
                }
        return best

    def get_all_character_states(self, novel_id: int) -> dict[str, dict]:
        """Get all character states for a novel, returning the latest state per character.

        Returns:
            Dict mapping character_name -> {"character_name": ..., "chapter_number": ..., "state": ...}
        """
        results = self.characters.get(
            where={"novel_id": novel_id},
            include=["documents", "metadatas"],
        )
        if not results["documents"]:
            return {}
        latest: dict[str, dict] = {}
        for doc, meta in zip(results["documents"], results["metadatas"]):
            name = meta.get("character_name", "")
            ch = meta.get("chapter_number", 0)
            if name not in latest or ch > latest[name]["chapter_number"]:
                latest[name] = {"character_name": name, "chapter_number": ch, "state": doc}
        return latest

    # ---- World Events ----

    def add_world_event(
        self,
        novel_id: int,
        chapter_number: int,
        event_description: str,
        event_type: str = "",
        importance: str = "normal",
    ):
        """Store a world event."""
        # Use a counter-based ID to avoid collisions
        existing = self.events.get(
            where={"novel_id": novel_id},
            include=["metadatas"],
        )
        event_index = len(existing["metadatas"]) if existing["metadatas"] else 0
        doc_id = f"novel_{novel_id}_event_{event_index}"

        metadata = {
            "novel_id": novel_id,
            "chapter_number": chapter_number,
            "event_type": event_type,
            "importance": importance,
        }
        self.events.upsert(
            ids=[doc_id],
            documents=[event_description],
            metadatas=[metadata],
        )

    # ---- Cleanup ----

    def delete_novel_data(self, novel_id: int):
        """Delete all data for a novel from all collections."""
        for collection in [self.summaries, self.characters, self.events]:
            results = collection.get(
                where={"novel_id": novel_id},
                include=[],
            )
            if results["ids"]:
                collection.delete(ids=results["ids"])

    def delete_chapter_data(self, novel_id: int, chapter_numbers: list[int]):
        """Delete data for specific chapters from all collections."""
        for ch_num in chapter_numbers:
            # Summary: deterministic ID
            summary_id = f"novel_{novel_id}_ch_{ch_num}"
            try:
                self.summaries.delete(ids=[summary_id])
            except Exception:
                pass

            # Characters & events: filter by metadata
            for collection in [self.characters, self.events]:
                try:
                    results = collection.get(
                        where={"$and": [
                            {"novel_id": novel_id},
                            {"chapter_number": ch_num},
                        ]},
                        include=[],
                    )
                    if results["ids"]:
                        collection.delete(ids=results["ids"])
                except Exception:
                    pass
