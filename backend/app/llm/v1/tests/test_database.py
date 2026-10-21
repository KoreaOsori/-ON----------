import json
import ssl
import unittest
from unittest.mock import AsyncMock, patch

from app.llm.v1.config import Settings
from app.llm.v1.database import CA_FILE, RDS, DatabaseConnectionError, create_database_engine, read_credentials


class SecretTests(unittest.TestCase):
    @patch("app.llm.v1.database.session_for")
    def test_only_credentials_are_taken_from_secret(self, session):
        client = session.return_value.client.return_value
        client.get_secret_value.return_value = {"SecretString": json.dumps({
            "username": "user", "password": "p@ss:/!", "host": "ignored", "dbname": "ignored"})}
        self.assertEqual(read_credentials(Settings(_env_file=None)), ("user", "p@ss:/!"))
        client.get_secret_value.assert_called_once_with(SecretId=RDS.secret_id, VersionStage="AWSCURRENT")
        client.close.assert_called_once()

    @patch("app.llm.v1.database.session_for")
    def test_empty_password_is_rejected_and_client_closed(self, session):
        client = session.return_value.client.return_value
        client.get_secret_value.return_value = {"SecretString": '{"username":"u","password":""}'}
        with self.assertRaises(ValueError):
            read_credentials(Settings(_env_file=None))
        client.close.assert_called_once()

    def test_bundled_ca_and_no_db_env_setting(self):
        context = ssl.create_default_context(cafile=str(CA_FILE))
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreater(context.cert_store_stats()["x509_ca"], 0)
        with patch.dict("os.environ", {"LLM_V1_DATABASE_URL": "invalid", "DATABASE_URL": "invalid"}):
            self.assertNotIn("database_url", Settings(_env_file=None).model_dump())
            self.assertEqual(RDS.database, "pill")


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.llm.v1.database.create_async_engine")
    @patch("app.llm.v1.database.asyncpg.connect", new_callable=AsyncMock)
    @patch("app.llm.v1.database.read_credentials")
    async def test_new_connections_refresh_password_and_verify_tls(self, credentials, connect, engine):
        credentials.side_effect = [("u", "old"), ("u", "new@:/!")]
        create_database_engine(Settings(_env_file=None))
        creator = engine.call_args.kwargs["async_creator"]
        await creator()
        await creator()
        self.assertEqual(credentials.call_count, 2)
        args = connect.call_args.kwargs
        self.assertEqual(args["host"], RDS.host)
        self.assertEqual(args["database"], "pill")
        self.assertEqual(args["password"], "new@:/!")
        self.assertTrue(args["ssl"].check_hostname)
        self.assertEqual(engine.call_args.args, ("postgresql+asyncpg://",))

    @patch("app.llm.v1.database.create_async_engine")
    @patch("app.llm.v1.database.read_credentials", side_effect=ValueError("SECRET MUST NOT LEAK"))
    async def test_failure_is_sanitized(self, credentials, engine):
        create_database_engine(Settings(_env_file=None))
        with self.assertRaises(DatabaseConnectionError) as caught:
            await engine.call_args.kwargs["async_creator"]()
        self.assertNotIn("SECRET MUST NOT LEAK", str(caught.exception))
