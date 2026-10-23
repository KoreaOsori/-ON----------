import json
import ssl
import unittest
from unittest.mock import AsyncMock, call, patch

from app.llm.v1.config import Settings
from app.llm.v1.database import CA_FILE, RDS, DatabaseConnectionError, create_database_engine, read_credentials


class SecretTests(unittest.TestCase):
    @patch("app.llm.v1.database.session_for")
    def test_credentials_and_host_are_read_from_their_secrets(self, session):
        client = session.return_value.client.return_value
        client.get_secret_value.side_effect = [
            {"SecretString": json.dumps({"username": "user", "password": "p@ss:/!", "host": "ignored"})},
            {"SecretString": json.dumps({"DB_HOST": "new-db.example", "DB_PASSWORD": "ignored"})}]
        self.assertEqual(read_credentials(Settings(_env_file=None)), ("user", "p@ss:/!", "new-db.example"))
        self.assertEqual(client.get_secret_value.call_args_list, [
            call(SecretId=RDS.secret_id, VersionStage="AWSCURRENT"),
            call(SecretId='pill-check/dev/app', VersionStage="AWSCURRENT")])
        client.close.assert_called_once()

    @patch("app.llm.v1.database.session_for")
    def test_invalid_host_never_falls_back_to_hardcoded_address(self, session):
        client = session.return_value.client.return_value
        for value in ({}, {'DB_HOST': ''}, {'DB_HOST': None}, {'DB_HOST': '  '}):
            with self.subTest(value=value):
                client.get_secret_value.side_effect = [
                    {'SecretString': '{"username":"u","password":"p"}'},
                    {'SecretString': json.dumps(value)}]
                with self.assertRaises((KeyError, ValueError)):
                    read_credentials(Settings(_env_file=None))

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
        credentials.side_effect = [("u", "old", "old-db.example"), ("u", "new@:/!", "new-db.example")]
        create_database_engine(Settings(_env_file=None))
        creator = engine.call_args.kwargs["async_creator"]
        await creator()
        await creator()
        self.assertEqual(credentials.call_count, 2)
        args = connect.call_args.kwargs
        self.assertEqual(connect.call_args_list[0].kwargs['host'], 'old-db.example')
        self.assertEqual(args["host"], 'new-db.example')
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
