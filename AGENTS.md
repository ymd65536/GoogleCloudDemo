
## 環境変数をセットする

次のエラーが出る場合は環境変数 `GOOGLE_CLOUD_PROJECT` をセットしてください。

```text
ValueError: 環境変数 GOOGLE_CLOUD_PROJECT が設定されていません
```

セットする方法は、ターミナルで次のコマンドを実行してください。

```bash
export PROJECT_ID=`gcloud config list --format 'value(core.project)'` && echo $PROJECT_ID
export GOOGLE_CLOUD_PROJECT=`gcloud config list --format 'value(core.project)'` && echo $GOOGLE_CLOUD_PROJECT
```

## Google Cloud SDKのセットアップ

環境変数GOOGLE_CLOUD_PROJECTがセットできない場合は、Google Cloud SDKをセットアップしてください。

```bash
gcloud init
```
