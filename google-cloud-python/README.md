# google-cloud-python サンプル集

`google-cloud-python` ライブラリを使って Google Cloud リソースを操作するサンプルスクリプト集です。

## 前提条件

### インストール

```bash
pip install google-cloud-compute google-cloud-artifact-registry
```

### 認証

[ADC (Application Default Credentials)](https://cloud.google.com/docs/authentication/application-default-credentials) を使用します。

```bash
gcloud auth application-default login
```

クォータプロジェクトの警告が出る場合は以下のコマンドを実行してください。

```bash
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

### 共通の環境変数

| 環境変数 | 説明 | デフォルト |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | プロジェクトID | ADCから自動取得 |
| `GOOGLE_CLOUD_ZONE` | ゾーン | スクリプトごとに異なる |
| `GOOGLE_CLOUD_INSTANCE` | 対象インスタンス名 | なし (必須) |

---

## Compute Engine

### インスタンス一覧の取得 (ゾーン指定)

指定ゾーンのインスタンス一覧を取得します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_ZONE=asia-northeast1-a  # 省略時は us-central1-a
python compute_engine.py
```

### インスタンス一覧の取得 (全ゾーン)

プロジェクト内の全ゾーンのインスタンスを一括取得します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python get_compute_engine.py
```

### インスタンスの作成

新しい Compute Engine インスタンスを作成します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python create_compute_engine.py --instance my-vm
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--instance` | インスタンス名 (必須) | 環境変数 `GOOGLE_CLOUD_INSTANCE` |
| `--zone` | ゾーン | `asia-northeast1-a` |
| `--machine-type` | マシンタイプ | `e2-micro` |
| `--image-family` | ブートイメージファミリー | `debian-12` |
| `--image-project` | イメージのプロジェクト | `debian-cloud` |
| `--disk-size` | ブートディスクサイズ (GB) | `10` |

```bash
# オプション指定の例
python create_compute_engine.py \
  --zone asia-northeast1-a \
  --instance my-vm \
  --machine-type e2-standard-2 \
  --disk-size 20
```

### インスタンスの起動

停止中 (TERMINATED) のインスタンスを起動します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python start_compute_engine.py --instance my-vm
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--instance` | インスタンス名 (必須) | 環境変数 `GOOGLE_CLOUD_INSTANCE` |
| `--zone` | ゾーン | `asia-northeast1-a` |

### インスタンスの停止

実行中 (RUNNING) のインスタンスを停止します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python stop_compute_engine.py --instance my-vm
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--instance` | インスタンス名 (必須) | 環境変数 `GOOGLE_CLOUD_INSTANCE` |
| `--zone` | ゾーン | `asia-northeast1-a` |

### インスタンスの再起動

インスタンスを再起動します。再起動方式を選択できます。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id

# ハードリセット (デフォルト): reset API で即時リセット
python restart_compute_engine.py --instance my-vm

# ソフトリスタート: グレースフルに stop → start
python restart_compute_engine.py --instance my-vm --soft
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--instance` | インスタンス名 (必須) | 環境変数 `GOOGLE_CLOUD_INSTANCE` |
| `--zone` | ゾーン | `asia-northeast1-a` |
| `--hard` | ハードリセット (即時リセット) | デフォルト |
| `--soft` | ソフトリスタート (stop → start) | — |

**ハードリセット vs ソフトリスタートの違い:**

| 方式 | API | 挙動 |
|---|---|---|
| `--hard` | `reset()` | インスタンスを強制リセット。状態は RUNNING のまま |
| `--soft` | `stop()` → `start()` | グレースフルなシャットダウン後に起動 |

---

## Artifact Registry

### リポジトリ一覧の取得

指定ロケーションの Artifact Registry リポジトリ一覧を取得します。

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=asia-northeast1  # 省略時は asia-northeast1
python artifact_registry.py
```

---

## ファイル構成

| ファイル | 説明 |
|---|---|
| `gcp_auth.py` | ADC を使った認証ヘルパー |
| `compute_engine.py` | インスタンス一覧取得 (ゾーン指定) |
| `get_compute_engine.py` | インスタンス一覧取得 (全ゾーン) |
| `create_compute_engine.py` | インスタンス作成 |
| `start_compute_engine.py` | インスタンス起動 |
| `stop_compute_engine.py` | インスタンス停止 |
| `restart_compute_engine.py` | インスタンス再起動 |
| `artifact_registry.py` | Artifact Registry リポジトリ一覧取得 |
