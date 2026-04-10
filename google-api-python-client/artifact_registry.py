"""
google-api-python-client を使って Artifact Registry のリポジトリ一覧を取得するサンプル

インストール:
    pip install google-api-python-client google-auth

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_LOCATION=us-central1  # 省略時は us-central1
    python main.py
"""

import os

import google.auth
from googleapiclient import discovery


def list_repositories(project_id: str, location: str) -> None:
    # Application Default Credentials (ADC) で認証
    credentials, _ = google.auth.default()

    # Discovery ドキュメントから Artifact Registry v1 クライアントを構築
    service = discovery.build("artifactregistry", "v1", credentials=credentials)

    parent = f"projects/{project_id}/locations/{location}"
    request = service.projects().locations().repositories().list(parent=parent)

    print(f"[google-api-python-client] Artifact Registry リポジトリ一覧 ({location})")
    print("-" * 60)

    while request is not None:
        response = request.execute()
        repositories = response.get("repositories", [])
        for repo in repositories:
            print(f"  名前    : {repo['name']}")
            print(f"  フォーマット: {repo.get('format', 'N/A')}")
            print(f"  説明    : {repo.get('description', '(なし)')}")
            print()

        # 次のページがあれば続けて取得
        request = service.projects().locations().repositories().list_next(
            previous_request=request, previous_response=response
        )


if __name__ == "__main__":
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise ValueError("環境変数 GOOGLE_CLOUD_PROJECT が設定されていません")

    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-northeast1")
    list_repositories(project_id, location)
