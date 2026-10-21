import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_silver as module


class SyncTests(unittest.TestCase):
    def run_sync(self, complete):
        args = Namespace(output="vector_pipeline/output", cache="cache", workers=4,
                         batch_size=128, retry_failed=False)
        sources = {t: f"s3://bucket/silver/{t}/2026-10-16/data.parquet"
                   for t in ("drug_product", "health_food_product")}
        with patch.multiple(module, connect=MagicMock(), check_config=Mock(),
                            silver_sources=Mock(return_value=sources),
                            mkdtemp=Mock(return_value="bundle"), prepare=Mock(),
                            validate_bundle=Mock(return_value=(Path("bundle"), {"complete": True})),
                            BedrockEmbedder=Mock(), embed_bundle=Mock(return_value={"complete": complete}),
                            ingest=Mock(return_value={"run_id": "run"})):
            result = module.sync_silver(args)
            if complete:
                self.assertTrue(module.ingest.call_args.kwargs["publish"])
            else:
                module.ingest.assert_not_called()
            self.assertEqual(module.prepare.call_args.args[0].expected_snapshot, "2026-10-16")
            return result

    def test_success_publishes(self):
        self.assertTrue(self.run_sync(True)["published"])

    def test_failed_embedding_does_not_publish(self):
        self.assertFalse(self.run_sync(False)["published"])
