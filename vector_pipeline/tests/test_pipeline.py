import argparse
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_documents import build_documents
from chunking import split_text
from config import EmbeddingConfig
from embedding import validate_vector
from run import prepare, validate_bundle


class DocumentTests(unittest.TestCase):
    def drug(self):
        return {"item_seq": "001", "item_name": "테스트정", "snapshot": date(2026, 10, 13),
                "doc_efficacy": [{"section_title": None, "article_title": "제목에만 있는 효능", "text": None}]}

    def test_title_only_article_is_preserved(self):
        chunks = list(build_documents(self.drug(), "drug", "local"))
        efficacy = next(c for c in chunks if c["section_type"] == "benefits")
        self.assertIn("제목에만 있는 효능", efficacy["content"])

    def test_snapshot_change_reuses_content_identity(self):
        row = self.drug()
        first = list(build_documents(row, "drug", "snapshot1"))
        row["snapshot"] = date(2026, 10, 14)
        second = list(build_documents(row, "drug", "snapshot2"))
        self.assertEqual([(c["chunk_id"], c["content_hash"]) for c in first],
                         [(c["chunk_id"], c["content_hash"]) for c in second])
        row["item_name"] = "변경된 제품명"
        changed = list(build_documents(row, "drug", "snapshot2"))
        self.assertNotEqual(first[0]["content_hash"], changed[0]["content_hash"])

    def test_product_types_do_not_collide(self):
        drug = list(build_documents(self.drug(), "drug", "local"))[0]
        health = list(build_documents({"prdlst_report_no": "001", "prdlst_nm": "테스트정",
                                       "snapshot": date(2026, 10, 13)}, "health_food", "local"))[0]
        self.assertNotEqual(drug["chunk_id"], health["chunk_id"])

    def test_null_dur_does_not_generate_safety_claim(self):
        row = self.drug()
        row.update(dur_pregnancy=None, dur_age=[])
        self.assertFalse(any(c["source_ref"].startswith("dur_") for c in build_documents(row, "drug", "local")))

    def test_dur_conditions_are_retained(self):
        row = self.drug()
        row["dur_pregnancy"] = [{"link_status": "조건별 복수", "ingredient_rules": [{"grade": "2", "remark": "조건 확인"}]}]
        chunk = next(c for c in build_documents(row, "drug", "local") if c["source_ref"].startswith("dur_"))
        self.assertIn("조건별 복수", chunk["content"])
        self.assertIn("조건 확인", chunk["content"])

    def test_split_covers_all_characters(self):
        text = "".join(chr(0xAC00 + i) for i in range(3000))
        chunks = list(split_text(text, 500, 50))
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertEqual(chunks[0] + "".join(c[50:] for c in chunks[1:]), text)

    def test_bad_vector_rejected(self):
        for vector in ([0, 0], [float("nan"), 1], [1]):
            with self.assertRaises(ValueError):
                validate_vector(vector, 2)

    def test_unsupported_model_rejected(self):
        with patch.dict(os.environ, {"EMBEDDING_MODEL_ID": "unknown"}):
            with self.assertRaises(ValueError):
                EmbeddingConfig.from_env()


class ParquetTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.drug = {"item_seq": "001", "item_name": "테스트정", "snapshot": date(2026, 10, 13)}
        self.health = {"prdlst_report_no": "001", "prdlst_nm": "테스트식품", "snapshot": date(2026, 10, 13)}
        pq.write_table(pa.Table.from_pylist([self.drug]), self.root / "drug.parquet")
        pq.write_table(pa.Table.from_pylist([self.health]), self.root / "health.parquet")
        self.args = argparse.Namespace(drug=str(self.root / "drug.parquet"), health_food=str(self.root / "health.parquet"),
                                       output=str(self.root / "output"), limit=0, max_chars=1800, overlap=150)

    def tearDown(self):
        self.temp.cleanup()

    def test_roundtrip_and_corruption(self):
        manifest = prepare(self.args)
        path, checked = validate_bundle(self.args.output)
        self.assertTrue(checked["complete"])
        self.assertEqual(manifest["chunks"], 2)
        with path.open("a", encoding="utf-8") as stream:
            stream.write("{}\n")
        with self.assertRaises(ValueError):
            validate_bundle(self.args.output)

    def test_sample_marked_incomplete(self):
        self.args.limit = 1
        self.assertFalse(prepare(self.args)["complete"])

    def test_duplicate_product_rejected(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist([self.drug, self.drug]), self.root / "drug.parquet")
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


if __name__ == "__main__":
    unittest.main()
