## Overview

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
