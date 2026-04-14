"""
google-cloud-python (google-cloud-sqladmin) を使って
Cloud SQL のインスタンスを作成するサンプル

インストール:
    pip install google-cloud-sqladmin

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_REGION=asia-northeast1      # 省略時は asia-northeast1
    export GOOGLE_CLOUD_SQL_INSTANCE=your-instance  # 作成するインスタンス名
    python create_cloud_sql.py

    # オプションで直接指定も可能
    python create_cloud_sql.py --instance my-db --db-version MYSQL_8_0 --tier db-f1-micro
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time

from google.cloud import sqladmin_v1

from gcp_auth import _get_credentials, _get_project_id


def _wait_for_operation(
    project_id: str,
    operation_name: str,
    credentials,
    interval: int = 5,
) -> None:
    """Cloud SQL オペレーションが DONE になるまでポーリングする。"""
    ops_client = sqladmin_v1.SqlOperationsServiceClient(credentials=credentials)
    while True:
        op = ops_client.get(
            sqladmin_v1.SqlOperationsGetRequest(
                project=project_id,
                operation=operation_name,
            )
        )
        if op.status == sqladmin_v1.Operation.SqlOperationStatus.DONE:
            if op.error:
                raise RuntimeError(
                    f"オペレーションが失敗しました: {op.error.errors}"
                )
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
    """新しい Cloud SQL インスタンスを作成する。

    Args:
        instance_name: 作成するインスタンス名
        region: リージョン (デフォルト: asia-northeast1)
        db_version: データベースバージョン (デフォルト: MYSQL_8_0)
        tier: マシンティア (デフォルト: db-f1-micro)
        storage_size_gb: ストレージサイズ GB (デフォルト: 10)
        storage_type: ストレージ種別 PD_SSD / PD_HDD (デフォルト: PD_SSD)
    """
    credentials = _get_credentials()
    project_id = _get_project_id()

    instance = sqladmin_v1.DatabaseInstance(
        name=instance_name,
        database_version=db_version,
        region=region,
        settings=sqladmin_v1.Settings(
            tier=tier,
            activation_policy="ALWAYS",
            data_disk_size_gb=storage_size_gb,
            data_disk_type=storage_type,
            backup_configuration=sqladmin_v1.BackupConfiguration(enabled=True),
            ip_configuration=sqladmin_v1.IpConfiguration(ipv4_enabled=True),
        ),
    )

    client = sqladmin_v1.SqlInstancesServiceClient(credentials=credentials)
    request = sqladmin_v1.SqlInstancesInsertRequest(
        project=project_id,
        body=instance,
    )

    print(f"[google-cloud-python] Cloud SQL インスタンスを作成します: {instance_name}")
    print(f"  プロジェクト  : {project_id}")
    print(f"  リージョン    : {region}")
    print(f"  DBバージョン  : {db_version}")
    print(f"  ティア        : {tier}")
    print(f"  ストレージ    : {storage_size_gb} GB ({storage_type})")

    operation = client.insert(request=request)
    _wait_for_operation(project_id, operation.name, credentials)

    print(f"  作成完了: {instance_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cloud SQL インスタンスを作成する")
    parser.add_argument(
        "--instance",
        default=os.environ.get("GOOGLE_CLOUD_SQL_INSTANCE"),
        required=not os.environ.get("GOOGLE_CLOUD_SQL_INSTANCE"),
        help="インスタンス名 (デフォルト: 環境変数 GOOGLE_CLOUD_SQL_INSTANCE)",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("GOOGLE_CLOUD_REGION", "asia-northeast1"),
        help="リージョン (デフォルト: 環境変数 GOOGLE_CLOUD_REGION または asia-northeast1)",
    )
    parser.add_argument(
        "--db-version",
        default="MYSQL_8_0",
        help="DBバージョン: MYSQL_8_0 / POSTGRES_15 / SQLSERVER_2022_EXPRESS など (デフォルト: MYSQL_8_0)",
    )
    parser.add_argument(
        "--tier",
        default="db-f1-micro",
        help="マシンティア (デフォルト: db-f1-micro)",
    )
    parser.add_argument(
        "--storage-size",
        type=int,
        default=10,
        help="ストレージサイズ GB (デフォルト: 10)",
    )
    parser.add_argument(
        "--storage-type",
        default="PD_SSD",
        choices=["PD_SSD", "PD_HDD"],
        help="ストレージ種別 (デフォルト: PD_SSD)",
    )
    args = parser.parse_args()

    create_instance(
        instance_name=args.instance,
        region=args.region,
        db_version=args.db_version,
        tier=args.tier,
        storage_size_gb=args.storage_size,
        storage_type=args.storage_type,
    )
