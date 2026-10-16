import unittest
from unittest.mock import AsyncMock, patch

from botocore.exceptions import NoCredentialsError

from app.llm.v1.aws_auth import RoleCredentialsError, session_for
from app.llm.v1.bedrock import Bedrock
from app.llm.v1.check_bedrock import check
from app.llm.v1.config import Settings


class AuthTests(unittest.TestCase):
    @patch("app.llm.v1.aws_auth.boto3.Session")
    def test_ec2_role_uses_refreshable_session_and_sigv4(self, factory):
        session = factory.return_value
        session.get_credentials.return_value.method = "iam-role"
        bedrock = Bedrock(Settings(_env_file=None))
        self.assertIs(bedrock.client, session.client.return_value)
        kwargs = session.client.call_args.kwargs
        self.assertEqual(kwargs["config"].signature_version, "v4")
        self.assertNotIn("aws_access_key_id", kwargs)
        session.get_credentials.return_value.get_frozen_credentials.assert_not_called()

    @patch("app.llm.v1.aws_auth.boto3.Session")
    def test_other_credential_sources_are_rejected(self, factory):
        for method in ("env", "shared-credentials-file", "assume-role", "container-role"):
            factory.return_value.get_credentials.return_value.method = method
            with self.assertRaises(RoleCredentialsError):
                session_for(Settings(_env_file=None))
        factory.return_value.client.assert_not_called()

    @patch("app.llm.v1.aws_auth.boto3.Session")
    def test_missing_credentials_fail(self, factory):
        factory.return_value.get_credentials.return_value = None
        with self.assertRaises(NoCredentialsError):
            session_for(Settings(_env_file=None))

    @patch("app.llm.v1.aws_auth.boto3.Session")
    def test_local_default_chain_is_opt_in(self, factory):
        factory.return_value.get_credentials.return_value.method = "sso"
        self.assertIs(session_for(Settings(_env_file=None, auth_mode="default_chain")), factory.return_value)


class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.llm.v1.check_bedrock.Bedrock")
    @patch("app.llm.v1.check_bedrock.session_for")
    async def test_identity_check_does_not_invoke_models(self, session_for_mock, bedrock):
        sts = session_for_mock.return_value.client.return_value
        sts.get_caller_identity.return_value = {"Arn": "arn:aws:sts::123:assumed-role/test/i-123", "Account": "123"}
        report = await check(Settings(_env_file=None))
        self.assertFalse(report["inference_verified"])
        bedrock.assert_not_called()
        sts.close.assert_called_once()

    @patch("app.llm.v1.check_bedrock.Bedrock")
    @patch("app.llm.v1.check_bedrock.session_for")
    async def test_invoke_checks_both_models_and_embedding(self, session_for_mock, bedrock):
        sts = session_for_mock.return_value.client.return_value
        sts.get_caller_identity.return_value = {"Arn": "role", "Account": "123"}
        bedrock.return_value.embed = AsyncMock(return_value=[0.1] * 1024)
        bedrock.return_value.generate = AsyncMock(return_value={"stop_reason": "end_turn", "answer": "OK", "usage": {}})
        report = await check(Settings(_env_file=None), invoke=True)
        self.assertTrue(report["inference_verified"])
        self.assertEqual(set(report["models"]), {"haiku", "sonnet"})
        self.assertEqual(bedrock.return_value.generate.await_count, 2)
