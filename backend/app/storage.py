"""Document storage: MongoDB when MONGODB_URI is set, otherwise local JSON files.

Both backends store plain dicts keyed by a string ``id`` so the rest of the app never
needs to know which one is active.
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from .config import get_settings

# Campaign data lives in DATA_FILE; each simulation collection gets its own file next to it
# (DATA_FILE stem + ".<collection>.json") so a simulation step only rewrites what it touched.
CORE_COLLECTIONS = ("candidates", "polls", "events", "reports")
SIM_COLLECTIONS = (
    "populations",
    "agents",
    "sim_runs",
    "sim_results",
    "sim_posts",
    "sim_ticks",
    "sim_state",
    "sim_checkpoints",
)
COLLECTIONS = CORE_COLLECTIONS + SIM_COLLECTIONS


class Store(Protocol):
    def find(
        self, coll: str, sort: str | None = None, fields: list[str] | None = None,
        limit: int | None = None, skip: int = 0, **filters: Any,
    ) -> list[dict]: ...
    def count(self, coll: str, **filters: Any) -> int: ...
    def get(self, coll: str, doc_id: str) -> dict | None: ...
    def insert(self, coll: str, doc: dict) -> dict: ...
    def insert_many(self, coll: str, docs: list[dict]) -> int: ...
    def upsert_many(self, coll: str, docs: list[dict]) -> int: ...
    def update(self, coll: str, doc_id: str, patch: dict) -> dict | None: ...
    def update_if(self, coll: str, doc_id: str, expect: dict, patch: dict) -> dict | None: ...
    def delete(self, coll: str, doc_id: str) -> bool: ...
    def delete_many(self, coll: str, **filters: Any) -> int: ...


def _matches(doc: dict, filters: dict[str, Any]) -> bool:
    return all(doc.get(k) == v for k, v in filters.items())


def _sort(docs: list[dict], sort: str | None) -> list[dict]:
    if not sort:
        return docs
    reverse = sort.startswith("-")
    key = sort.lstrip("-")
    return sorted(docs, key=lambda d: (d.get(key) is None, d.get(key)), reverse=reverse)


def _project(doc: dict, fields: list[str] | None) -> dict:
    if not fields:
        return dict(doc)
    return {k: doc[k] for k in ("id", *fields) if k in doc}


class JsonFileStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        core = json.loads(self.path.read_text() or "{}") if self.path.exists() else {}
        self._data: dict[str, dict[str, dict]] = {c: core.get(c, {}) for c in CORE_COLLECTIONS}
        for coll in SIM_COLLECTIONS:
            p = self._file(coll)
            self._data[coll] = json.loads(p.read_text() or "{}") if p.exists() else {}

    def _file(self, coll: str) -> Path:
        return self.path if coll in CORE_COLLECTIONS else self.path.with_name(f"{self.path.stem}.{coll}.json")

    def _flush(self, coll: str) -> None:
        target = self._file(coll)
        if coll in CORE_COLLECTIONS:
            text = json.dumps({c: self._data[c] for c in CORE_COLLECTIONS}, indent=1, default=str)
        else:
            text = json.dumps(self._data[coll], separators=(",", ":"), default=str)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(target)

    def find(
        self, coll: str, sort: str | None = None, fields: list[str] | None = None,
        limit: int | None = None, skip: int = 0, **filters: Any,
    ) -> list[dict]:
        with self._lock:
            docs = [_project(d, fields) if not sort else dict(d) for d in self._data[coll].values() if _matches(d, filters)]
        docs = _sort(docs, sort)
        if sort and fields:
            docs = [_project(d, fields) for d in docs]
        end = None if limit is None else skip + limit
        return docs[skip:end]

    def count(self, coll: str, **filters: Any) -> int:
        with self._lock:
            return sum(1 for d in self._data[coll].values() if _matches(d, filters))

    def get(self, coll: str, doc_id: str) -> dict | None:
        with self._lock:
            doc = self._data[coll].get(doc_id)
            return dict(doc) if doc else None

    def insert(self, coll: str, doc: dict) -> dict:
        with self._lock:
            self._data[coll][doc["id"]] = doc
            self._flush(coll)
        return doc

    def insert_many(self, coll: str, docs: list[dict]) -> int:
        with self._lock:
            for doc in docs:
                self._data[coll][doc["id"]] = doc
            if docs:
                self._flush(coll)
        return len(docs)

    def upsert_many(self, coll: str, docs: list[dict]) -> int:
        return self.insert_many(coll, docs)

    def update(self, coll: str, doc_id: str, patch: dict) -> dict | None:
        with self._lock:
            doc = self._data[coll].get(doc_id)
            if doc is None:
                return None
            doc.update(patch)
            self._flush(coll)
            return dict(doc)

    def update_if(self, coll: str, doc_id: str, expect: dict, patch: dict) -> dict | None:
        """Compare-and-set: apply ``patch`` only if every field in ``expect`` still matches."""
        with self._lock:
            doc = self._data[coll].get(doc_id)
            if doc is None or not _matches(doc, expect):
                return None
            doc.update(patch)
            self._flush(coll)
            return dict(doc)

    def delete(self, coll: str, doc_id: str) -> bool:
        with self._lock:
            existed = self._data[coll].pop(doc_id, None) is not None
            if existed:
                self._flush(coll)
            return existed

    def delete_many(self, coll: str, **filters: Any) -> int:
        with self._lock:
            doomed = [k for k, d in self._data[coll].items() if _matches(d, filters)]
            for k in doomed:
                del self._data[coll][k]
            if doomed:
                self._flush(coll)
            return len(doomed)


class MongoStore:
    def __init__(self, uri: str, db_name: str):
        from pymongo import ASCENDING, DESCENDING, MongoClient

        self._asc, self._desc = ASCENDING, DESCENDING
        self.client = MongoClient(uri, serverSelectionTimeoutMS=8000, appname="undercurrent")
        self.db = self.client[db_name]
        for coll in ("polls", "events", "reports"):
            self.db[coll].create_index("candidate_id")
        self.db["agents"].create_index([("population_id", ASCENDING), ("index", ASCENDING)])
        self.db["populations"].create_index("candidate_id")
        for key in ("population_id", "candidate_id"):
            self.db["sim_runs"].create_index(key)
        for coll in ("sim_results", "sim_posts", "sim_ticks", "sim_checkpoints"):
            self.db[coll].create_index("run_id")

    @staticmethod
    def _out(doc: dict | None) -> dict | None:
        if doc is None:
            return None
        doc.pop("_id", None)
        return doc

    def find(
        self, coll: str, sort: str | None = None, fields: list[str] | None = None,
        limit: int | None = None, skip: int = 0, **filters: Any,
    ) -> list[dict]:
        projection = {"_id": 0, "id": 1, **{f: 1 for f in fields}} if fields else None
        cursor = self.db[coll].find(filters, projection)
        if sort:
            cursor = cursor.sort(sort.lstrip("-"), self._desc if sort.startswith("-") else self._asc)
        if skip:
            cursor = cursor.skip(skip)
        if limit is not None:
            cursor = cursor.limit(limit)
        return [self._out(d) for d in cursor]  # type: ignore[misc]

    def count(self, coll: str, **filters: Any) -> int:
        return self.db[coll].count_documents(filters)

    def get(self, coll: str, doc_id: str) -> dict | None:
        return self._out(self.db[coll].find_one({"_id": doc_id}))

    def insert(self, coll: str, doc: dict) -> dict:
        self.db[coll].insert_one({"_id": doc["id"], **doc})
        return doc

    def insert_many(self, coll: str, docs: list[dict]) -> int:
        if not docs:
            return 0
        self.db[coll].insert_many([{"_id": d["id"], **d} for d in docs])
        return len(docs)

    def upsert_many(self, coll: str, docs: list[dict]) -> int:
        from pymongo import ReplaceOne

        if not docs:
            return 0
        self.db[coll].bulk_write([ReplaceOne({"_id": d["id"]}, {"_id": d["id"], **d}, upsert=True) for d in docs], ordered=False)
        return len(docs)

    def update(self, coll: str, doc_id: str, patch: dict) -> dict | None:
        from pymongo import ReturnDocument

        return self._out(
            self.db[coll].find_one_and_update({"_id": doc_id}, {"$set": patch}, return_document=ReturnDocument.AFTER)
        )

    def update_if(self, coll: str, doc_id: str, expect: dict, patch: dict) -> dict | None:
        from pymongo import ReturnDocument

        return self._out(
            self.db[coll].find_one_and_update(
                {"_id": doc_id, **expect}, {"$set": patch}, return_document=ReturnDocument.AFTER
            )
        )

    def delete(self, coll: str, doc_id: str) -> bool:
        return self.db[coll].delete_one({"_id": doc_id}).deleted_count > 0

    def delete_many(self, coll: str, **filters: Any) -> int:
        return self.db[coll].delete_many(filters).deleted_count


@lru_cache
def get_store() -> Store:
    s = get_settings()
    if s.mongodb_uri:
        return MongoStore(s.mongodb_uri, s.mongodb_db)
    return JsonFileStore(s.data_file)
