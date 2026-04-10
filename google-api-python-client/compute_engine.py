"""
google-api-python-client を使って Compute Engine のインスタンス状態を取得するサンプル

インストール:
    pip install google-api-python-client google-auth

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_ZONE=us-central1-a  # 省略時は us-central1-a
    python compute_engine.py
"""

import os

import google.auth
from googleapiclient import discovery


def list_instances(project_id: str, zone: str) -> None:
    # Application Default Credentials (ADC) で認証
    credentials, _ = google.auth.default()

    # Discovery ドキュメントから Compute Engine v1 クライアントを構築
    service = discovery.build("compute", "v1", credentials=credentials)

    request = service.instances().list(project=project_id, zone=zone)

    print(f"[google-api-python-client] Compute Engine インスタンス一覧 ({zone})")
    print("-" * 60)

    while request is not None:
        response = request.execute()
        instances = response.get("items", [])

        if not instances:
            print("  インスタンスが見つかりませんでした")
            break

        for instance in instances:
            print(f"  名前    : {instance['name']}")
            print(f"  状態    : {instance['status']}")
            print(f"  マシンタイプ: {instance['machineType'].split('/')[-1]}")
            print(f"  ゾーン  : {instance['zone'].split('/')[-1]}")
            print()

        # 次のページがあれば続けて取得
        request = service.instances().list_next(
            previous_request=request, previous_response=response
        )


if __name__ == "__main__":
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise ValueError("環境変数 GOOGLE_CLOUD_PROJECT が設定されていません")

    zone = os.environ.get("GOOGLE_CLOUD_ZONE", "us-central1-a")
    list_instances(project_id, zone)
