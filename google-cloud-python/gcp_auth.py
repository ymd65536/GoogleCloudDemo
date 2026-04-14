"""
Google Cloud 認証ヘルパーモジュール。
ADC (Application Default Credentials) を使用して認証情報とプロジェクトIDを取得する。
"""

from google import auth
from google.auth.transport.requests import AuthorizedSession


def _get_credentials():
    """ADC を使用して認証情報を取得する。"""
    credentials, _ = auth.default()
    return credentials


def _get_project_id():
    """ADC からプロジェクトIDを取得する。環境変数が優先される。"""
    _, project_id = auth.default()
    return project_id


def _get_project_number() -> str:
    """Resource Manager REST API を呼び出してプロジェクト番号を返す。"""
    import os
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or _get_project_id()
    session = _get_authed_session()
    resp = session.get(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}"
    )
    resp.raise_for_status()
    return resp.json()["projectNumber"]


def _get_authed_session() -> AuthorizedSession:
    """requests ベースの認証済みセッションを返す。
    google.auth.transport.requests を使うため httplib2 の SSL 問題が発生しない。
    Cloud SQL Admin REST API など discovery 系の呼び出しに使用する。
    """
    credentials, project_id = auth.default()
    # クォータプロジェクトを設定することで 403 エラーを防ぐ
    if project_id and hasattr(credentials, "with_quota_project"):
        credentials = credentials.with_quota_project(project_id)
    return AuthorizedSession(credentials)
