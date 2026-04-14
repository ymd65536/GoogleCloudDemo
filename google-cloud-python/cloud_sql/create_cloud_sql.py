"""
google.auth.transport.requests (Google Cloud Python Client) を使って
Cloud SQL Admin REST API でインスタンスを作成するサンプル

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    uv run python cloud_sql/create_cloud_sql.py --instance my-db
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gcp_auth import _get_authed_session, _get_project_id

BASE_URL = "https://sqladmin.googleapis.com/v1"


def _wait_for_operation(session, project_id: str, operation_name: str, interval: int = 5) -> None:
    """Cloud SQL オペレーションが DONE になるまでポーリングする。"""
    url = f"{BASE_URL}/projects/{project_id}/operations/{operation_name}"
    while True:
        op = session.get(url).json()
        if op.get("status") == "DONE":
            if op.get("error"):
                raise RuntimeError(f"オペレーションが失敗しました: {op['error']}")
            break
        time.sleep(interval)


def create_instance(
    instance_name: str,
    region: str = "asia-northeast1",
    db_version: str = "MYSQL_8_0",
    tier: str = "db-f1-micro",
    storage_size_gb: int = 10,
    storage_type: str = "PD_SSD",
) -> None:
    """新しい Cloud SQL インスタンスを作成する。"""
    session = _get_authed_session()
    project_id = _get_project_id()
    if not project_id:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT が設定されていません")

    body = {
        "name": instance_name,
        "databaseVersion": db_version,
        "region": region,
        "settings": {
            "tier": tier,
            "activationPolicy": "ALWAYS",
            "dataDiskSizeGb": str(storage_size_gb),
            "dataDiskType": storage_type,
            "backupConfiguration": {"enabled": True},
            "ipConfiguration": {"ipv4Enabled": True},
        },
    }

    print(f"[google-cloud-python] Cloud SQL インスタンスを作成します: {instance_name}")
    print(f"  プロジェクト  : {project_id}")
    print(f"  リージョン    : {region}")
    print(f"  DBバージョン  : {db_version}")
    print(f"  ティア        : {tier}")
    print(f"  ストレージ    : {storage_size_gb} GB ({storage_type})")

    resp = session.post(f"{BASE_URL}/projects/{project_id}/instances", json=body)
    resp.raise_for_status()
    operation = resp.json()
    _wait_for_operation(session, project_id, operation["name"])
    print(f"  作成完了: {instance_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cloud SQL インスタンスを作成する")
    parser.add_argument(
        "--instance",
        default=os.environ.get("GOOGLE_CLOUD_SQL_INSTANCE"),
        required=not os.environ.get("GOOGLE_CLOUD_SQL_INSTANCE"),
        help="インスタンス名 (デフォルト: 環境変数 GOOGLE_CLOUD_SQL_INSTANCE)",
    )
    parser.add_argument("--region", default=os.environ.get("GOOGLE_CLOUD_REGION", "asia-northeast1"))
    parser.add_argument("--db-version", default="MYSQL_8_0")
    parser.add_argument("--tier", default="db-f1-micro")
    parser.add_argument("--storage-size", type=int, default=10)
    parser.add_argument("--storage-type", default="PD_SSD", choices=["PD_SSD", "PD_HDD"])
    args = parser.parse_args()

    create_instance(
        instance_name=args.instance,
        region=args.region,
        db_version=args.db_version,
        tier=args.tier,
        storage_size_gb=args.storage_size,
        storage_type=args.storage_type,
    )
