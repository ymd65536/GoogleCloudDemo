"""
google.auth.transport.requests (Google Cloud Python Client) を使って
Cloud SQL Admin REST API でインスタンスを再起動するサンプル

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    uv run python cloud_sql/restart_cloud_sql.py --instance my-db
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gcp_auth import _get_authed_session, _get_project_id

BASE_URL = "https://sqladmin.googleapis.com/v1"


def _wait_for_operation(session, project_id: str, operation_name: str, interval: int = 5) -> None:
    url = f"{BASE_URL}/projects/{project_id}/operations/{operation_name}"
    while True:
        op = session.get(url).json()
        if op.get("status") == "DONE":
            if op.get("error"):
                raise RuntimeError(f"オペレーションが失敗しました: {op['error']}")
            break
        time.sleep(interval)


def restart_instance(instance_name: str) -> None:
    """指定したインスタンスを再起動する。"""
    session = _get_authed_session()
    project_id = _get_project_id()

    print(f"[google-cloud-python] Cloud SQL インスタンスを再起動します: {instance_name}")

    resp = session.post(
        f"{BASE_URL}/projects/{project_id}/instances/{instance_name}/restart"
    )
    resp.raise_for_status()
    operation = resp.json()
    _wait_for_operation(session, project_id, operation["name"])
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
