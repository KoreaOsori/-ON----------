# pill_model — 약ON 낱알 식별 워커

알약 사진 2장(앞·뒤) → 각인 OCR + CNN 외형 + RRF 결합 → 후보와 대화 단계 응답.
별도 EC2에서 Docker로 실행하고, 메인 백엔드와는 HTTP(8000)로만 연결한다. 규칙은 `claude.md`, 순서는 `plan.md`.

## 인프라 (`infra/terraform`, 별도 스택)

팀 스택과 같은 state 버킷을 쓰되 키가 다르다: `pill-check/dev/pill-model.tfstate`.
팀 VPC·서브넷·백엔드 SG·데이터 버킷은 `data`로 읽기만 하고, 아래만 새로 만든다.

| 자원 | 이름 |
|---|---|
| EC2 (t3.medium, AL2023, gp3 30GB, IMDSv2, 키 페어 없음) | `pill-worker` |
| 보안 그룹 (인바운드: 백엔드 SG → TCP 8000만) | `pill-worker-sg` |
| IAM 역할·인스턴스 프로필 (SSM + 필요한 S3 경로만) | `pill-worker-role` |
| 모델 버킷 (`models/v5/…`, `crops/…`) | `pill-worker-model-<계정 ID>` |

```bash
cd pill_model/infra/terraform
cp backend.hcl.example backend.hcl            # 팀 state 버킷 이름
cp terraform.tfvars.example terraform.tfvars  # 백엔드 EC2의 VPC·서브넷·SG ID, 데이터 버킷
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan                    # 생성만 있고 변경·삭제 0 인지 확인
terraform apply tfplan                        # 사용자가 직접 실행
terraform output                              # worker_url, worker_connect 등
```

접속: `terraform output -raw worker_connect` 의 명령 (SSM). Docker는 `ec2-user` 그룹에 있으므로 접속 후 `sudo su - ec2-user`.

### 정리(destroy) 전 주의
모델 버킷은 `force_destroy = false` 라서 객체가 남아 있으면 `terraform destroy` 가 실패한다(동의받은 crop 실수 삭제 방지).
지워도 되는지 확인한 뒤 버킷을 직접 비우고 destroy 한다.
