import os

from google.oauth2 import service_account
from googleapiclient import discovery

import certifi
import google_auth_httplib2
import httplib2


def action(parameters, credentials):
    """
    google-api-client を使って OS Config の patchJobs.execute を実行する
    """
    # 1. 認証情報とクライアントの初期化
    # credentials は以下のどちらかを想定する:
    # - service account info dict（from_service_account_info 用）
    # - google.auth.credentials.Credentials（ADC 用）
    if isinstance(credentials, dict):
        sa_creds = service_account.Credentials.from_service_account_info(credentials)
        project_id = credentials["project_id"]
    else:
        sa_creds = credentials
        project_id = parameters.get("project_id")
        if not project_id:
            raise ValueError("project_id が指定されていません（parameters['project_id'] を渡してください）")

    # 環境変数が既に設定されている場合はそれを優先し、未設定時のみ certifi にフォールバック
    _CA_BUNDLE = (
        os.environ.get("REQUESTS_CA_BUNDLE")
        or os.environ.get("SSL_CERT_FILE")
        or certifi.where()
    )

    authorized_http = google_auth_httplib2.AuthorizedHttp(
        sa_creds, http=httplib2.Http(ca_certs=_CA_BUNDLE)
    )

    # osconfig v1 サービスをビルド
    osconfig = discovery.build('osconfig', 'v1', http=authorized_http)

    # ExecutePatchJobRequest
    # parameters から必要なものを組み立てる（CLI側で渡す想定）
    patch_job_id = parameters.get("patch_job_id")
    if not patch_job_id:
        raise ValueError("patch_job_id が指定されていません（parameters['patch_job_id'] を渡してください）")

    instance_filter = parameters.get("instance_filter")
    if not instance_filter:
        raise ValueError("instance_filter が指定されていません（parameters['instance_filter'] を渡してください）")

    patch_config = parameters.get("patch_config")
    if not patch_config:
        raise ValueError("patch_config が指定されていません（parameters['patch_config'] を渡してください）")

    body = {
        "id": patch_job_id,
        "instanceFilter": instance_filter,
        "patchConfig": patch_config,
    }

    try:
        print(f"Sending patchJobs.execute via google-api-client (project={project_id}, patchJobId={patch_job_id})...")

        # 3. API実行
        # patchJobs.execute は PatchJob を返す
        patch_job = osconfig.projects().patchJobs().execute(
            parent=f"projects/{project_id}",
            body=body,
        ).execute()

        return f"patchJob を作成/実行しました: {patch_job.get('name', patch_job_id)}"

    except Exception as e:
        return f"API実行失敗: {str(e)}"
