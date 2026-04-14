"""
google-cloud-python (google-cloud-sqladmin) を使って
Cloud SQL のインスタンスを起動するサンプル

Cloud SQL の「起動」は activationPolicy を ALWAYS に設定することで実現します。

インストール:
    pip install google-cloud-sqladmin

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_SQL_INSTANCE=your-instance  # 起動するインスタンス名
    python start_cloud_sql.py

    # オプションで直接指定も可能
    python start_cloud_sql.py --instance my-db
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


def start_instance(instance_name: str) -> None:
    """指定したインスタンスを起動する (activationPolicy を ALWAYS に設定)。"""
    credentials = _get_credentials()
    project_id = _get_project_id()

    client = sqladmin_v1.SqlInstancesServiceClient(credentials=credentials)

    # activationPolicy を ALWAYS に変更して起動
    patch_body = sqladmin_v1.DatabaseInstance(
        settings=sqladmin_v1.Settings(activation_policy="ALWAYS"),
    )
    request = sqladmin_v1.SqlInstancesPatchRequest(
        project=project_id,
        instance=instance_name,
        body=patch_body,
    )

    print(f"[google-cloud-python] Cloud SQL インスタンスを起動します: {instance_name}")

    operation = client.patch(request=request)
    _wait_for_operation(project_id, operation.name, credentials)

    print(f"  起動完了: {instance_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cloud SQL インスタンスを起動する")
    parser.add_argument(
        "--instance",
        default=os.environ.get("GOOGLE_CLOUD_SQL_INSTANCE"),
        required=not os.environ.get("GOOGLE_CLOUD_SQL_INSTANCE"),
        help="インスタンス名 (デフォルト: 環境変数 GOOGLE_CLOUD_SQL_INSTANCE)",
    )
    args = parser.parse_args()

    start_instance(args.instance)
