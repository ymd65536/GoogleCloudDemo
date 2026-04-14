"""
google.auth.transport.requests (Google Cloud Python Client) を使って
Cloud SQL Admin REST API でインスタンス一覧を取得するサンプル

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    uv run python cloud_sql/list_cloud_sql.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gcp_auth import _get_authed_session, _get_project_id

BASE_URL = "https://sqladmin.googleapis.com/v1"


def list_instances() -> None:
    """プロジェクト内の Cloud SQL インスタンス一覧を表示する。"""
    session = _get_authed_session()
    project_id = _get_project_id()

    resp = session.get(f"{BASE_URL}/projects/{project_id}/instances")
    resp.raise_for_status()
    data = resp.json()

    print("[google-cloud-python] Cloud SQL インスタンス一覧")
    print("-" * 60)

    items = data.get("items", [])
    if not items:
        print("  インスタンスが見つかりませんでした")
        return

    for instance in items:
        settings = instance.get("settings", {})
        print(f"  名前          : {instance['name']}")
        print(f"  状態          : {instance.get('state', 'UNKNOWN')}")
        print(f"  DBバージョン  : {instance.get('databaseVersion', 'UNKNOWN')}")
        print(f"  リージョン    : {instance.get('region', 'UNKNOWN')}")
        print(f"  ティア        : {settings.get('tier', 'UNKNOWN')}")
        print()


if __name__ == "__main__":
    list_instances()
