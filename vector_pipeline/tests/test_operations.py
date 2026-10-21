import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_documents import DurConditionError, dur_blocks
from bundle import prepare, records, validate_bundle
from config import EmbeddingConfig
from cache import EmbeddingCache
from embed_pipeline import embed_bundle, fill_cache
from lifecycle import prune_candidates, rollback
from search import find_products, like_literal, rank_exact, retrieve
from test_pipeline import FakeEmbedder, TempTests, drug
from vector_store import publish_run


class DurBoundaryTests(unittest.TestCase):
    def test_budget_301_has_specific_error_302_is_valid(self):
        row = {"dur_age": [{"ingr_name": "성분A", "prohbt_content": "주의사항 " * 100}]}
        context = "DUR 주의 유형: 연령\n제품 규칙 조건:\n성분: 성분A"
        with self.assertRaises(DurConditionError):
            list(dur_blocks(row, len(context) + 1 + 301, 150))
        self.assertTrue(list(dur_blocks(row, len(context) + 1 + 302, 150)))

    def test_rejected_rule_does_not_drop_next_rule(self):
        row = {"dur_age": [{"ingr_name": "가" * 2000, "prohbt_content": "보존할 원문"},
                           {"ingr_name": "성분B", "prohbt_content": "다음 규칙"}]}
        rejected = []
        chunks = list(dur_blocks(row, 1800, 150, rejected.append))
        self.assertEqual(len(rejected), 1)
        self.assertIn("보존할 원문", rejected[0]["body"])
        self.assertEqual(len(chunks), 1)
        self.assertIn("다음 규칙", chunks[0][2])


class QuarantineTests(TempTests):
    def setUp(self):
        import argparse
        import pyarrow as pa
        import pyarrow.parquet as pq
        super().setUp()
        self.row = drug()
        health = {"prdlst_report_no": "001", "prdlst_nm": "테스트식품", "snapshot": date(2026, 10, 13)}
        pq.write_table(pa.Table.from_pylist([self.row]), self.root / "drug.parquet")
        pq.write_table(pa.Table.from_pylist([health]), self.root / "health.parquet")
        self.args = argparse.Namespace(drug=str(self.root / "drug.parquet"), health_food=str(self.root / "health.parquet"),
                                       output=str(self.root / "bundle"), limit=0, max_chars=1800, overlap=150, min_chars=900)

    def test_prepare_quarantine_is_valid_but_not_publishable(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.row["dur_age"] = [{"ingr_name": "가" * 2000, "prohbt_content": "위험 조건"}]
        pq.write_table(pa.Table.from_pylist([self.row]), self.root / "drug.parquet")
        manifest = prepare(self.args)
        root, _ = validate_bundle(self.args.output)
        self.assertEqual(manifest["rejected_rules"], 1)
        self.assertFalse(manifest["complete"])
        self.assertEqual(manifest["sources"]["drug"]["processed_rows"], 1)
        self.assertEqual(list(records(root / "rejects.jsonl"))[0]["product_key"], "drug:001")
        with self.assertRaises(ValueError):
            publish_run(None, "run", manifest)

    def test_one_embedding_failure_does_not_block_other_documents(self):
        root = Path(self.args.output)
        manifest = prepare(self.args)
        docs = list(records(root / "documents.jsonl"))
        config = EmbeddingConfig("test", "test", 2)
        cache = self.root / "embeddings.sqlite"
        failing = FakeEmbedder(fail=docs[1]["content"])
        first = embed_bundle(root, manifest, config, failing, cache, workers=1, batch_size=1)
        self.assertEqual(len(failing.calls), len(docs))
        self.assertEqual(first["failed"], 1)
        self.assertFalse(first["complete"])
        self.assertTrue(cache.with_suffix(".failures.jsonl").exists())
        skip = FakeEmbedder()
        second = embed_bundle(root, manifest, config, skip, cache)
        self.assertFalse(skip.calls)
        self.assertEqual(second["skipped_recorded_failures"], 1)
        healthy = FakeEmbedder()
        third = embed_bundle(root, manifest, config, healthy, cache, retry_failed=True)
        self.assertTrue(third["complete"])
        self.assertEqual(healthy.calls, [docs[1]["content"]])
        self.assertEqual(cache.with_suffix(".failures.jsonl").read_text(), "")


class SearchTests(unittest.TestCase):
    def test_name_uses_overview_and_parameterized_predicate(self):
        conn = MagicMock()
        conn.execute.return_value.fetchall.side_effect = [[], [("drug:1", "약A", "회사", "drug")]]
        result = find_products(conn, "run", "약%_", limit=10)
        self.assertEqual(result["mode"], "prefix")
        sql, params = conn.execute.call_args.args
        self.assertIn("section_type='overview'", sql)
        self.assertIn("lower(product_name) LIKE %s", sql)
        self.assertEqual(params[-2], "약\\%\\_%")
        self.assertEqual(like_literal("a\\b"), "a\\\\b")

    def test_exact_ranking_filters_before_topk(self):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        rank_exact(conn, "run", [1, 0], product_keys=["drug:1"], section_type="usage")
        sql, params = conn.execute.call_args.args
        self.assertIn("candidates AS MATERIALIZED", sql)
        self.assertLess(sql.index("l.product_key=ANY"), sql.index("ORDER BY distance"))
        self.assertIn(["drug:1"], params)
        self.assertIn("usage", params)

    def test_name_not_found_never_falls_back_to_global(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = ("active",)
        embedder = FakeEmbedder()
        with patch("search.connect") as connection, patch("search.check_config"), \
                patch("search.find_products", return_value={"products": [], "truncated": False}), \
                patch("search.rank_exact") as rank:
            connection.return_value.__enter__.return_value = conn
            result = retrieve(EmbeddingConfig("test", "test", 2), "복용법", "없는약", embedder=embedder)
            self.assertEqual(result["results"], [])
            self.assertFalse(embedder.calls)
            rank.assert_not_called()

    def test_product_resolution_scopes_following_search(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = ("active",)
        with patch("search.connect") as connection, patch("search.check_config"), \
                patch("search.find_products", return_value={"products": [{"product_key": "drug:1"}], "truncated": False}), \
                patch("search.rank_exact", return_value=[]) as rank:
            connection.return_value.__enter__.return_value = conn
            retrieve(EmbeddingConfig("test", "test", 2), "복용법", "약", embedder=FakeEmbedder())
            self.assertEqual(rank.call_args.args[4], ["drug:1"])


class GlobalFailureTests(TempTests):
    def test_permission_error_is_not_quarantined_as_bad_document(self):
        class AccessDenied(Exception):
            response = {"Error": {"Code": "AccessDeniedException"}}
        embedder = MagicMock()
        embedder.embed.side_effect = AccessDenied()
        with EmbeddingCache(self.root / "cache.sqlite", EmbeddingConfig("test", "test", 2)) as cache:
            with self.assertRaises(RuntimeError):
                fill_cache([{"content_hash": "h", "content": "text"}], cache, embedder, continue_on_error=True)
            self.assertEqual(cache.failed_hashes(["h"]), set())


class LifecycleTests(unittest.TestCase):
    def test_explicit_rollback_allows_older_complete_run_with_audit(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [("complete", 3, 4), (date(2026, 10, 14),)]
        publish_run(conn, "old", {"complete": True, "documents": 3, "links": 4, "snapshot": "2026-10-13"}, rollback=True, reason="검증된 이전 버전")
        event = next(c for c in conn.execute.call_args_list if "publication_events" in c.args[0])
        self.assertEqual(event.args[1], ("old", "rollback", "검증된 이전 버전"))

    def test_rollback_reason_required(self):
        with self.assertRaises(ValueError):
            rollback(None, "old", " ")

    def test_prune_protects_active_and_retained_runs(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=60)
        rows = [("active", "complete", old), ("latest", "complete", now),
                ("old", "complete", old), ("unfinished", "loading", old), ("interrupted", "pruning", now)]
        targets = prune_candidates(rows, "active", 1, 30, now=now)
        self.assertEqual(set(targets), {"old", "interrupted"})
        self.assertIn("unfinished", prune_candidates(rows, "active", 1, 30, True, now))


if __name__ == "__main__":
    unittest.main()
