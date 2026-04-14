"""
google-cloud-python (google-cloud-sqladmin) を使って
Cloud SQL のインスタンスを再起動するサンプル

インストール:
    pip install google-cloud-sqladmin

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_SQL_INSTANCE=your-instance  # 再起動するインスタンス名
    python restart_cloud_sql.py

    # オプションで直接指定も可能
    python restart_cloud_sql.py --instance my-db
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


def restart_instance(instance_name: str) -> None:
    """指定したインスタンスを再起動する (RUNNABLE → 再起動 → RUNNABLE)。"""
    credentials = _get_credentials()
    project_id = _get_project_id()

    client = sqladmin_v1.SqlInstancesServiceClient(credentials=credentials)
    request = sqladmin_v1.SqlInstancesRestartRequest(
        project=project_id,
        instance=instance_name,
    )

    print(f"[google-cloud-python] Cloud SQL インスタンスを再起動します: {instance_name}")

    operation = client.restart(request=request)
    _wait_for_operation(project_id, operation.name, credentials)

    print(f"  再起動完了: {instance_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cloud SQL インスタンスを再起動する")
    parser.add_argument(
        "--instance",
        default=os.environ.get("GOOGLE_CLOUD_SQL_INSTANCE"),
        required=not os.environ.get("GOOGLE_CLOUD_SQL_INSTANCE"),
        help="インスタンス名 (デフォルト: 環境変数 GOOGLE_CLOUD_SQL_INSTANCE)",
    )
    args = parser.parse_args()

    restart_instance(args.instance)
