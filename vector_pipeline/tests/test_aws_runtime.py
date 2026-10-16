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
        s3.get_object.return_value = {"Body": io.BytesIO(json.dumps({
            "snapshot": "2026-10-15", "tables": {"drug_product": "2026-10-15",
                                                  "health_food_product": health}}).encode())}
        return s3

    def test_completed_pointer_resolves_both_tables(self):
        s3 = self.pointer()
        sources = silver_sources("data-bucket", s3=s3)
        self.assertEqual(sources["drug_product"], "s3://data-bucket/silver/drug_product/snapshot=2026-10-15/data.parquet")
        self.assertTrue(s3.get_object.return_value["Body"].closed)

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
