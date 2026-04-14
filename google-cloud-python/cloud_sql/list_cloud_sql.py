"""
google-cloud-python (google-cloud-sqladmin) を使って
Cloud SQL のインスタンス一覧を取得するサンプル

インストール:
    pip install google-cloud-sqladmin

使い方:
    export GOOGLE_CLOUD_PROJECT=your-project-id
    python list_cloud_sql.py
"""

from google.cloud import sqladmin_v1

from gcp_auth import _get_credentials, _get_project_id


def list_instances() -> None:
    """プロジェクト内の Cloud SQL インスタンス一覧を表示する。"""
    credentials = _get_credentials()
    project_id = _get_project_id()

    client = sqladmin_v1.SqlInstancesServiceClient(credentials=credentials)
    request = sqladmin_v1.SqlInstancesListRequest(project=project_id)

    response = client.list(request=request)

    print("[google-cloud-python] Cloud SQL インスタンス一覧")
    print("-" * 60)

    if not response.items:
        print("  インスタンスが見つかりませんでした")
        return

    for instance in response.items:
        print(f"  名前          : {instance.name}")
        print(f"  状態          : {instance.state.name}")
        print(f"  DBバージョン  : {instance.database_version.name}")
        print(f"  リージョン    : {instance.region}")
        print(f"  ティア        : {instance.settings.tier}")
        print()


if __name__ == "__main__":
    list_instances()
