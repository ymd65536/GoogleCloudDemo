"""
google-api-python-client を使って
Compute Engine のインスタンスを起動するサンプル

インストール:
    pip install google-api-python-client google-auth

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_ZONE=us-central1-a      # 省略時は us-central1-a
    export GOOGLE_CLOUD_INSTANCE=your-instance  # 起動するインスタンス名
    python start_compute_engine.py
"""

import os
import time

import google.auth
from googleapiclient import discovery


def wait_for_operation(service, project_id: str, zone: str, operation_name: str) -> None:
    """ゾーンオペレーションが完了するまでポーリングする。"""
    while True:
        result = (
            service.zoneOperations()
            .get(project=project_id, zone=zone, operation=operation_name)
            .execute()
        )
        if result["status"] == "DONE":
            if "error" in result:
                raise RuntimeError(f"オペレーションが失敗しました: {result['error']}")
            return
        time.sleep(2)


def start_instance(project_id: str, zone: str, instance_name: str) -> None:
    """指定したインスタンスを起動する (TERMINATED → RUNNING)。"""
    credentials, _ = google.auth.default()
    service = discovery.build("compute", "v1", credentials=credentials)

    print(f"[google-api-python-client] インスタンスを起動します: {instance_name} ({zone})")

    response = (
        service.instances()
        .start(project=project_id, zone=zone, instance=instance_name)
        .execute()
    )

    # オペレーションが完了するまで待機
    wait_for_operation(service, project_id, zone, response["name"])

    print(f"  起動完了: {instance_name}")


if __name__ == "__main__":
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise ValueError("環境変数 GOOGLE_CLOUD_PROJECT が設定されていません")

    zone = os.environ.get("GOOGLE_CLOUD_ZONE", "us-central1-a")

    instance_name = os.environ.get("GOOGLE_CLOUD_INSTANCE")
    if not instance_name:
        raise ValueError("環境変数 GOOGLE_CLOUD_INSTANCE が設定されていません")

    start_instance(project_id, zone, instance_name)
