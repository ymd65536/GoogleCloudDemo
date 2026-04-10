## Overview

## Google Cloudのサービス

SDKで利用できるサービスの中でも使いそうなサービスをピックアップしてプログラムを書きます。

- Artifact Registry
- Compute Engine
- Cloud Run

- Cloud Storage
- Cloud Pub/Sub
- Cloud Functions
- Cloud Build

google-apiまたはgoogle-cloud-pythonを使用して、これらのサービスを操作するサンプルコードを提供します。

## install gcloud

First, install gcloud using curl.

```bash
curl -sSL https://sdk.cloud.google.com | bash && exec -l $SHELL && gcloud init
```

Alternatively, you can install gcloud using the following command, which will disable prompts during installation.

```bash
curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts
```

Note: When using `--disable-prompts`, the PATH setup is skipped. Add the following to your `~/.bashrc` manually:

```bash
if [ -f "$HOME/google-cloud-sdk/path.bash.inc" ]; then
  source "$HOME/google-cloud-sdk/path.bash.inc"
fi
if [ -f "$HOME/google-cloud-sdk/completion.bash.inc" ]; then
  source "$HOME/google-cloud-sdk/completion.bash.inc"
fi
```

Then reload your shell:

```bash
source ~/.bashrc
```

Then, log in with gcloud.

```bash
gcloud auth login
```

If you are running this command in an environment without a web browser, such as a remote server, you can use the following command to log in without launching a browser.

```bash
gcloud auth login --no-launch-browser
```

You can find your Project ID on the Google Cloud Welcome page.
※Check [welcome google cloud](https://console.cloud.google.com/welcome?)

The correct command is:
```bash
gcloud config set project PROJECT_ID
```

For example, if your project ID is `my-awesome-project-123`, you would run:
```bash
gcloud config set project my-awesome-project-123
```

This command sets the active Google Cloud project for all subsequent `gcloud` commands.

Next, you will set up Application Default Credentials (ADC).

```bash
gcloud auth application-default login
```

This completes the setup. / The setup is now complete.

### Google Cloud Project ID

If you are not using a `.env` file in this project, set the following environment variables directly in your terminal before running the Slack app.
If you are using a `.env` file, you can skip this step as the `PROJECT_ID` will be set automatically when you run the app.

Set the `PROJECT_ID` environment variables.

```bash
export PROJECT_ID=`gcloud config list --format 'value(core.project)'` && echo $PROJECT_ID
export GOOGLE_CLOUD_PROJECT=`gcloud config list --format 'value(core.project)'` && echo $GOOGLE_CLOUD_PROJECT
```

## Troubleshooting

### SSL CERTIFICATE_VERIFY_FAILED

企業プロキシ環境などで自己署名CA証明書によるSSLインターセプトが行われている場合、以下のエラーが発生することがあります。

```
ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain
```

この場合、接続先からCA証明書を取得してシステムの信頼ストアに追加することで解消できます。

1. プロキシのCA証明書を取得する（例: `oauth2.googleapis.com` に接続する場合）

```bash
echo | openssl s_client -connect oauth2.googleapis.com:443 -showcerts 2>/dev/null \
  | awk '/BEGIN CERTIFICATE/,/END CERTIFICATE/{print}' \
  | awk 'BEGIN{c=0} /BEGIN CERT/{c++} c==2{print}' \
  | sudo tee /usr/local/share/ca-certificates/proxy-ca.crt
```

2. システムの証明書ストアを更新する

```bash
sudo update-ca-certificates
```

3. `httplib2` が使用する `certifi` のバンドルにも追加する

`httplib2` はシステム証明書ストアではなく `certifi` のバンドル（`cacert.pem`）を参照するため、以下のコマンドも実行する必要があります。

```bash
cat /usr/local/share/ca-certificates/proxy-ca.crt >> $(python3 -c "import certifi; print(certifi.where())")
```

> **注意:** `certifi` をアップグレードすると追記した内容が消えます。アップグレード後は再度このコマンドを実行してください。

これにより、SSLエラーが解消されます。
