import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aws_runtime import database_options, silver_sources


class RuntimeTests(unittest.TestCase):
    def pointer(self, health="2026-10-15"):
        s3 = Mock()
        s3.get_paginator.return_value.paginate.side_effect = lambda **kw: [{"Contents": [
            {"Key": kw["Prefix"] + "snapshot=" + (health if "health_food" in kw["Prefix"] else "2026-10-15") + "/data.parquet", "Size": 100}]}]
        return s3

    def test_completed_pointer_resolves_both_tables(self):
        s3 = self.pointer()
        sources = silver_sources("data-bucket", s3=s3)
        self.assertEqual(sources["drug_product"], "s3://data-bucket/silver/drug_product/snapshot=2026-10-15/data.parquet")
        s3.get_object.assert_not_called()

    def test_latest_common_date_across_pages(self):
        s3 = Mock()
        def pages(**kw):
            dates = ["2026-10-14", "2026-10-15"]
            if "drug_product" in kw["Prefix"]:
                dates.append("2026-10-16")
            return [{"Contents": [{"Key": kw["Prefix"] + d + "/data.parquet", "Size": 100}]} for d in dates]
        s3.get_paginator.return_value.paginate.side_effect = pages
        sources = silver_sources("data-bucket", s3=s3)
        self.assertTrue(all("/2026-10-15/" in v for v in sources.values()))

    def test_empty_and_invalid_objects_not_selected(self):
        s3 = Mock()
        s3.get_paginator.return_value.paginate.side_effect = lambda **kw: [{"Contents": [
            {"Key": kw["Prefix"] + "2026-10-16/data.parquet", "Size": 0},
            {"Key": kw["Prefix"] + "latest/data.parquet", "Size": 100}]}]
        with self.assertRaises(ValueError):
            silver_sources("data-bucket", s3=s3)

    def test_mixed_snapshot_is_rejected(self):
        with self.assertRaises(ValueError):
            silver_sources("data-bucket", s3=self.pointer("2026-10-14"))

    def test_changed_pointer_rejected_when_pinned(self):
        with self.assertRaises(ValueError):
            silver_sources("data-bucket", snapshot="2026-10-14", s3=self.pointer())

    def test_secret_rotation_without_environment(self):
        secrets = Mock()
        secrets.get_secret_value.side_effect = [
            {"SecretString": json.dumps({"username": "master", "password": p})} for p in ("old", "new")]
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(database_options(secrets)["password"], "old")
            options = database_options(secrets)
        self.assertEqual(options["password"], "new")
        self.assertEqual(options["dbname"], "pill")
        self.assertEqual(options["sslmode"], "verify-full")
        secrets.get_secret_value.assert_called_with(SecretId="rds!db-71cf9992-e13e-4601-88da-425ac219f336")

    def test_database_settings_ignore_environment(self):
        secrets = Mock()
        secrets.get_secret_value.return_value = {"SecretString": '{"username":"user","password":"secret"}'}
        with patch.dict("os.environ", {"PGHOST": "pg", "DB_HOST": "alias", "PGDATABASE": "pill", "PGUSER": "user"}, clear=True):
            self.assertEqual(database_options(secrets)["host"], "pill-check-dev-postgres.c43ekyi6yiie.us-east-1.rds.amazonaws.com")

    def test_embedding_config_without_environment(self):
        from config import EmbeddingConfig
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(EmbeddingConfig.from_env().region, "us-east-1")
