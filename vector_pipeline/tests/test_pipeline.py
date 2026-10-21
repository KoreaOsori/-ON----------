import argparse
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_documents import build_documents
from bundle import file_hash, prepare, records, validate_bundle
from cache import EmbeddingCache
from chunking import pack_articles, split_text
from config import EmbeddingConfig
from embed_pipeline import fill_cache
from embedding import validate_vector
from vector_store import publish_run, run_identity, write_vectors

TEST_ROOT = Path(__file__).resolve().parents[1] / "output" / "tests"


def drug():
    return {"item_seq": "001", "item_name": "테스트정", "entp_name": "업체A", "snapshot": date(2026, 10, 13),
            "doc_efficacy": [{"section_title": None, "article_title": "제목에만 있는 효능", "text": None}]}


class DocumentTests(unittest.TestCase):
    def test_title_only_article_is_preserved(self):
        chunks = list(build_documents(drug(), "drug", "local"))
        self.assertIn("제목에만 있는 효능", next(c for c in chunks if c["section_type"] == "benefits")["content"])

    def test_generic_names_share_description_not_overview(self):
        first = list(build_documents(drug(), "drug", "s1"))
        row = drug()
        row.update(item_seq="002", item_name="다른제네릭정", entp_name="업체B", snapshot=date(2026, 10, 14))
        second = list(build_documents(row, "drug", "s2"))
        self.assertEqual(first[1]["content_hash"], second[1]["content_hash"])
        self.assertNotEqual(first[0]["content_hash"], second[0]["content_hash"])
        self.assertNotEqual(first[1]["chunk_id"], second[1]["chunk_id"])
        self.assertNotIn("업체A", first[1]["content"])

    def test_snapshot_is_not_embedding_input(self):
        row = drug()
        first = list(build_documents(row, "drug", "s1"))
        row["snapshot"] = date(2026, 10, 14)
        second = list(build_documents(row, "drug", "s2"))
        self.assertEqual([c["content_hash"] for c in first], [c["content_hash"] for c in second])

    def test_null_dur_not_safe_claim(self):
        row = drug()
        row.update(dur_pregnancy=None, dur_age=[])
        self.assertFalse(any(c["source_refs"][0].startswith("dur_") for c in build_documents(row, "drug", "local")))

    def test_dur_codes_metadata_and_alternative_conditions(self):
        row = drug()
        row["dur_pregnancy"] = [{"rule_key": "INTERNAL001", "mix_ingr_codes": ["CODE001"],
                                  "link_status": "조건별 복수", "prohbt_content": "공통 주의",
                                  "ingredient_rules": [{"grade": "1", "remark": "조건A"},
                                                       {"grade": "2", "remark": "조건B"}]}]
        chunks = [c for c in build_documents(row, "drug", "local") if c["source_refs"][0].startswith("dur_")]
        self.assertEqual(len(chunks), 2)
        self.assertIn("등급: 1", chunks[0]["content"])
        self.assertNotIn("조건B", chunks[0]["content"])
        self.assertIn("공통 주의", chunks[1]["content"])
        self.assertNotIn("INTERNAL001", chunks[0]["content"])
        self.assertNotIn("mix_ingr_codes", chunks[0]["content"])
        self.assertEqual(chunks[0]["metadata"]["parent"]["link_status"], "조건별 복수")

    def test_long_dur_repeats_conditions(self):
        row = drug()
        row["dur_age"] = [{"ingr_name": "성분A", "ingredient_rules": [
            {"age_base": "12세 미만", "prohbt_content": "긴 주의사항입니다. " * 200}]}]
        chunks = [c for c in build_documents(row, "drug", "local", 500, 50, 200) if c["source_refs"][0].startswith("dur_")]
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all("12세 미만" in c["content"] and "성분A" in c["content"] for c in chunks))

    def test_merge_retains_all_article_references(self):
        articles = [(f"doc/{i}", f"조항{i}: " + "가" * 80) for i in range(6)]
        chunks = list(pack_articles(articles, 600, 50, 400))
        self.assertLess(len(chunks), len(articles))
        self.assertEqual({r for refs, _ in chunks for r in refs}, {r for r, _ in articles})
        self.assertTrue(all(len(text) <= 600 for _, text in chunks))
        self.assertTrue(all(text in "\n".join(t for _, t in chunks) for _, text in articles))

    def test_split_covers_all_characters(self):
        text = "".join(chr(0xAC00 + i) for i in range(3000))
        chunks = list(split_text(text, 500, 50))
        self.assertEqual(chunks[0] + "".join(c[50:] for c in chunks[1:]), text)

    def test_bad_vector_rejected(self):
        for vector in ([0, 0], [float("nan"), 1], [1]):
            with self.assertRaises(ValueError):
                validate_vector(vector, 2)

    def test_region_falls_back_to_settings(self):
        with patch.dict(os.environ, {"AWS_REGION": "", "BEDROCK_REGION": ""}):
            self.assertEqual(EmbeddingConfig.from_env().region, "us-east-1")


class TempTests(unittest.TestCase):
    def setUp(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()


class ParquetTests(TempTests):
    def setUp(self):
        super().setUp()
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.row = drug()
        self.health = {"prdlst_report_no": "001", "prdlst_nm": "테스트식품", "snapshot": date(2026, 10, 13)}
        pq.write_table(pa.Table.from_pylist([self.row]), self.root / "drug.parquet")
        pq.write_table(pa.Table.from_pylist([self.health]), self.root / "health.parquet")
        self.args = argparse.Namespace(drug=str(self.root / "drug.parquet"), health_food=str(self.root / "health.parquet"),
                                       output=str(self.root / "bundle"), limit=0, max_chars=1800, overlap=150, min_chars=900)

    def test_roundtrip_and_corruption(self):
        prepare(self.args)
        root, m = validate_bundle(self.args.output)
        self.assertTrue(m["complete"])
        self.assertEqual(m["documents"], 3)
        with (root / "documents.jsonl").open("a", encoding="utf-8") as f:
            f.write("{}\n")
        with self.assertRaises(ValueError):
            validate_bundle(root)

    def test_cross_product_dedup_preserves_links(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        row2 = {**self.row, "item_seq": "002", "item_name": "다른제품"}
        pq.write_table(pa.Table.from_pylist([self.row, row2]), self.root / "drug.parquet")
        m = prepare(self.args)
        root, _ = validate_bundle(self.args.output)
        self.assertEqual(m["documents"], 4)
        self.assertEqual(m["links"], 5)
        shared = [r for r in records(root / "links.jsonl") if r["section_type"] == "benefits"]
        self.assertEqual(len({r["content_hash"] for r in shared}), 1)
        self.assertEqual(len({r["product_key"] for r in shared}), 2)

    def test_sample_marked_incomplete(self):
        self.args.limit = 1
        self.assertFalse(prepare(self.args)["complete"])

    def test_duplicate_product_rejected(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist([self.row, self.row]), self.root / "drug.parquet")
        with self.assertRaises(ValueError):
            prepare(self.args)
        self.assertFalse((Path(self.args.output) / "manifest.json").exists())

    def test_snapshot_mismatch_rejected(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.health["snapshot"] = date(2026, 10, 14)
        pq.write_table(pa.Table.from_pylist([self.health]), self.root / "health.parquet")
        with self.assertRaises(ValueError):
            prepare(self.args)

    def test_invalid_link_rejected_even_with_updated_file_hash(self):
        m = prepare(self.args)
        root = Path(self.args.output)
        links = list(records(root / "links.jsonl"))
        links[0]["content_hash"] = "missing"
        (root / "links.jsonl").write_text("".join(json.dumps(x) + "\n" for x in links), encoding="utf-8")
        m["files"]["links.jsonl"] = file_hash(root / "links.jsonl")
        (root / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        with self.assertRaises(ValueError):
            validate_bundle(root)


class FakeEmbedder:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []
        self.active = self.peak = 0
        self.lock = threading.Lock()

    def embed(self, text):
        with self.lock:
            self.calls.append(text)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.01)
            if text == self.fail:
                raise RuntimeError("simulated API outage")
            return [0.6, 0.8]
        finally:
            with self.lock:
                self.active -= 1


class ResumeTests(TempTests):
    def test_failure_preserves_completed_results_and_resumes(self):
        config = EmbeddingConfig("test", "test-model", 2)
        path = self.root / "cache.sqlite"
        docs = [{"content_hash": str(i), "content": str(i)} for i in range(10)]
        failed = FakeEmbedder(fail="3")
        with EmbeddingCache(path, config) as cache:
            with self.assertRaises(RuntimeError):
                fill_cache(docs, cache, failed, workers=2)
        healthy = FakeEmbedder()
        with EmbeddingCache(path, config) as cache:
            saved = cache.get_many([d["content_hash"] for d in docs])
            self.assertTrue(saved)
            self.assertNotIn("3", saved)
            missing = [d for d in docs if d["content_hash"] not in saved]
            fill_cache(missing, cache, healthy, workers=2)
            self.assertEqual(len(cache.get_many([d["content_hash"] for d in docs])), 10)
            self.assertFalse(set(healthy.calls) & saved.keys())
        self.assertLessEqual(failed.peak, 2)
        self.assertLessEqual(healthy.peak, 2)

    def test_cache_model_isolation(self):
        path = self.root / "cache.sqlite"
        with EmbeddingCache(path, EmbeddingConfig("test", "a", 2)) as cache:
            cache.put("hash", [1, 1])
        with EmbeddingCache(path, EmbeddingConfig("test", "b", 2)) as cache:
            self.assertEqual(cache.get_many(["hash"]), {})


class FakeConnection:
    def __init__(self, fail_copy=False):
        self.fail_copy = fail_copy
        self.events = []
    def transaction(self):
        conn = self
        class Transaction:
            def __enter__(self):
                conn.events.append("begin")
            def __exit__(self, typ, value, tb):
                conn.events.append("rollback" if typ else "commit")
        return Transaction()
    def execute(self, sql, params=None):
        self.events.append(sql)
    def cursor(self):
        return self
    def copy(self, sql):
        conn = self
        class Copy:
            def __enter__(self):
                return self
            def write_row(self, row):
                if conn.fail_copy:
                    raise RuntimeError("disconnected")
                conn.events.append("copy-row")
            def __exit__(self, *args):
                pass
        return Copy()


class StoreTests(unittest.TestCase):
    def test_batch_checkpoint_is_atomic(self):
        batch = [{"content_hash": "h", "content": "text", "product_type": "drug", "section_type": "usage"}]
        conn = FakeConnection()
        write_vectors(conn, batch, {"h": [1, 1]}, "run", 1)
        self.assertEqual(conn.events[-1], "commit")
        self.assertIn("documents_loaded", conn.events[-2])
        failed = FakeConnection(fail_copy=True)
        with self.assertRaises(RuntimeError):
            write_vectors(failed, batch, {"h": [1, 1]}, "run", 1)
        self.assertEqual(failed.events[-1], "rollback")
        self.assertFalse(any("documents_loaded" in e for e in failed.events))

    def test_sample_cannot_publish(self):
        with self.assertRaises(ValueError):
            publish_run(None, "run", {"complete": False})

    def test_unfinished_run_cannot_replace_active_snapshot(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = ("loading", 3, 2)
        with self.assertRaises(ValueError):
            publish_run(conn, "run", {"complete": True, "documents": 3, "links": 4})
        self.assertFalse(any("INSERT INTO product_search.active_snapshot" in c.args[0] for c in conn.execute.call_args_list))

    def test_old_snapshot_cannot_replace_newer_snapshot(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [("complete", 3, 4), (date(2026, 10, 14),)]
        with self.assertRaises(ValueError):
            publish_run(conn, "run", {"complete": True, "documents": 3, "links": 4, "snapshot": "2026-10-13"})
        self.assertFalse(any("INSERT INTO product_search.active_snapshot" in c.args[0] for c in conn.execute.call_args_list))

    def test_complete_run_switches_only_active_pointer(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [("complete", 3, 4), None]
        publish_run(conn, "run", {"complete": True, "documents": 3, "links": 4, "snapshot": "2026-10-13"})
        writes = [c.args[0] for c in conn.execute.call_args_list if c.args[0].startswith("INSERT")]
        self.assertEqual(len(writes), 2)
        self.assertIn("publication_events", writes[0])
        self.assertIn("active_snapshot", writes[1])

    def test_run_identity_covers_manifest_and_model(self):
        a = EmbeddingConfig("test", "a", 2)
        b = EmbeddingConfig("test", "b", 2)
        self.assertNotEqual(run_identity({"files": "a"}, a), run_identity({"files": "b"}, a))
        self.assertNotEqual(run_identity({"files": "a"}, a), run_identity({"files": "a"}, b))


if __name__ == "__main__":
    unittest.main()
