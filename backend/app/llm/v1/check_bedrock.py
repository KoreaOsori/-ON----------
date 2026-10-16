"""Run on EC2: identity-only by default; --invoke explicitly tests paid inference."""
import argparse
import asyncio
import json

from botocore.exceptions import BotoCoreError, ClientError

from .aws_auth import RoleCredentialsError, client_config, session_for
from .bedrock import Bedrock
from .config import Settings


async def check(settings, invoke=False):
    session = await asyncio.to_thread(session_for, settings)
    sts = session.client("sts", config=client_config())
    try:
        identity = await asyncio.to_thread(sts.get_caller_identity)
    finally:
        sts.close()
    report = {"auth_mode": settings.auth_mode, "region": settings.region,
              "caller_arn": identity["Arn"], "account": identity["Account"],
              "inference_verified": False}
    if invoke:
        bedrock = Bedrock(settings)
        try:
            vector = await bedrock.embed("연결 확인")
            report["embedding_dimensions"] = len(vector)
            report["models"] = {}
            for alias in ("haiku", "sonnet"):
                result = await bedrock.generate(settings.model_id(alias), "Reply with OK only.", "Connection test")
                if result["stop_reason"] != "end_turn" or not result["answer"].strip():
                    raise ValueError(f"{alias}: 응답 미완료")
                report["models"][alias] = {"model_id": settings.model_id(alias), "usage": result["usage"]}
            report["inference_verified"] = True
        finally:
            if "client" in bedrock.__dict__:
                bedrock.client.close()
    return report


def main():
    parser = argparse.ArgumentParser(description="EC2 역할 인증 및 Bedrock 연결 확인 (DB 불필요)")
    parser.add_argument("--invoke", action="store_true", help="유료 호출: Titan 1회 + Haiku 1회 + Sonnet 1회")
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(check(Settings(), args.invoke)), ensure_ascii=False, indent=2))
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "unknown")
        print(f"AWS 확인 실패 ({code}): 역할 권한·모델 접근·리전·SCP를 확인하세요.")
        raise SystemExit(1) from None
    except RoleCredentialsError as error:
        print(str(error))
        raise SystemExit(1) from None
    except (BotoCoreError, ValueError, OSError):
        print("연결 확인 실패: EC2 instance profile, IMDS, 네트워크 및 SDK 설정을 확인하세요.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
