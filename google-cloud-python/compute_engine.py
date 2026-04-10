"""
google-cloud-python (google-cloud-compute) を使って
Compute Engine のインスタンス状態を取得するサンプル

インストール:
    pip install google-cloud-compute

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_ZONE=us-central1-a  # 省略時は us-central1-a
    python compute_engine.py
"""

import os

from google.cloud import compute_v1


def list_instances(project_id: str, zone: str) -> None:
    # InstancesClient は ADC を自動的に使用する
    client = compute_v1.InstancesClient()

    request = compute_v1.ListInstancesRequest(project=project_id, zone=zone)

    print(f"[google-cloud-python] Compute Engine インスタンス一覧 ({zone})")
    print("-" * 60)

    # ページネーションは自動処理される (イテレータとして返る)
    instances = list(client.list(request=request))

    if not instances:
        print("  インスタンスが見つかりませんでした")
        return

    for instance in instances:
        # status は文字列 (RUNNING / TERMINATED / STOPPED など)
        print(f"  名前    : {instance.name}")
        print(f"  状態    : {instance.status}")
        print(f"  マシンタイプ: {instance.machine_type.split('/')[-1]}")
        print(f"  ゾーン  : {instance.zone.split('/')[-1]}")
        print()


if __name__ == "__main__":
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise ValueError("環境変数 GOOGLE_CLOUD_PROJECT が設定されていません")

    zone = os.environ.get("GOOGLE_CLOUD_ZONE", "us-central1-a")
    list_instances(project_id, zone)
