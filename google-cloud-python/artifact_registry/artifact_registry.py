"""
google-cloud-python (google-cloud-artifact-registry) を使って
Artifact Registry のリポジトリ一覧を取得するサンプル

インストール:
    pip install google-cloud-artifact-registry

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_LOCATION=us-central1  # 省略時は us-central1
    python main.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import google.auth
from google.cloud import artifactregistry_v1


def list_repositories(project_id: str, location: str) -> None:
    # ArtifactRegistryClient は ADC を自動的に使用する
    credentials, auth_project_id = google.auth.default()
    client = artifactregistry_v1.ArtifactRegistryClient(credentials=credentials)

    parent = f"projects/{project_id}/locations/{location}"
    request = artifactregistry_v1.ListRepositoriesRequest(parent=parent)

    print(f"[google-cloud-python] Artifact Registry リポジトリ一覧 ({location})")
    print("-" * 60)

    # ページネーションは自動処理される (イテレータとして返る)
    for repo in client.list_repositories(request=request):
        print(f"  名前    : {repo.name}")
        print(
            f"  フォーマット: {artifactregistry_v1.Repository.Format(repo.format_).name}")
        print(f"  説明    : {repo.description or '(なし)'}")
        print()


if __name__ == "__main__":
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise ValueError("環境変数 GOOGLE_CLOUD_PROJECT が設定されていません")

    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-northeast1")
    list_repositories(project_id, location)
