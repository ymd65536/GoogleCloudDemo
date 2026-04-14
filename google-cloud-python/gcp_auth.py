"""
Google Cloud 認証ヘルパーモジュール。
ADC (Application Default Credentials) を使用して認証情報とプロジェクトIDを取得する。
"""

from google import auth


def _get_credentials():
    """ADC を使用して認証情報を取得する。"""
    credentials, _ = auth.default()
    return credentials


def _get_project_id():
    """ADC からプロジェクトIDを取得する。環境変数が優先される。"""
    _, project_id = auth.default()
    return project_id
