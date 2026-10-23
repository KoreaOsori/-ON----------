"""
S3 입출력 — 업로드 사진 읽기(pill/·prescription/), 동의한 알약 조각 저장(모델 버킷 crops/).

- 사진은 메모리(bytes)로만 다루고 디스크에 쓰지 않는다 (plan.md 3-2)
- object_key 형식은 백엔드 presign 과 같음: {purpose}/YYYY/MM/DD/{owner}/{uuid}.{jpg|png|webp}
- crop 경로에는 사용자 ID 를 넣지 않는다 (claude.md 2 저장 정책)
"""
import io
import os
import re
import uuid
from datetime import UTC, datetime

KEY_RE = re.compile(r"^(pill|prescription)/\d{4}/\d{2}/\d{2}/[A-Za-z0-9-]{1,64}/[0-9a-f-]{36}\.(jpg|jpeg|png|webp)$")


class BadKey(ValueError):
    pass


class NotFound(Exception):
    pass


class TooLarge(Exception):
    pass


class Storage:
    def __init__(self, settings):
        self.s = settings
        self._s3 = None

    def s3(self):
        if self._s3 is None:
            import boto3
            self._s3 = boto3.client("s3", region_name=self.s.aws_region)
        return self._s3

    @staticmethod
    def check_key(key, purpose):
        """/pill/* 는 pill/, /rx/* 는 prescription/ 만 허용. '..' 같은 경로 조작도 정규식에서 걸러짐"""
        if not KEY_RE.match(key or "") or not key.startswith(purpose + "/"):
            raise BadKey(key)

    def read(self, key, purpose):
        self.check_key(key, purpose)
        if self.s.local_upload_dir:
            path = os.path.join(self.s.local_upload_dir, *key.split("/"))
            if not os.path.isfile(path):
                raise NotFound(key)
            if os.path.getsize(path) > self.s.max_bytes:
                raise TooLarge(key)
            with open(path, "rb") as f:
                return f.read()
        from botocore.exceptions import ClientError
        try:
            obj = self.s3().get_object(Bucket=self.s.upload_bucket, Key=key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "AccessDenied"):
                # 업로드 전이거나 수명주기로 지워진 경우 (권한 밖 경로도 같은 응답으로)
                raise NotFound(key) from e
            raise
        if obj.get("ContentLength", 0) > self.s.max_bytes:
            obj["Body"].close()
            raise TooLarge(key)
        return obj["Body"].read()

    def save_crop(self, rgba, side):
        """배경 제거된 알약 조각(알파 영역만 잘라낸 PNG) 저장 → 저장한 key"""
        box = rgba.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
        if box is None:
            return None
        buf = io.BytesIO()
        rgba.crop(box).save(buf, format="PNG")
        key = f"crops/{datetime.now(UTC):%Y/%m/%d}/{uuid.uuid4()}_{side}.png"
        if self.s.local_upload_dir:
            path = os.path.join(self.s.local_upload_dir, *key.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(buf.getvalue())
        else:
            self.s3().put_object(Bucket=self.s.model_bucket, Key=key, Body=buf.getvalue(), ContentType="image/png")
        return key
