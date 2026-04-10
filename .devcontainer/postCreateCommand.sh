# bin/bash
curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts
echo 'source "$HOME/google-cloud-sdk/path.zsh.inc"' >> ~/.zshrc
echo 'source "$HOME/google-cloud-sdk/completion.zsh.inc"' >> ~/.zshrc
echo 'source "$HOME/google-cloud-sdk/path.bash.inc"' >> ~/.bashrc
echo 'source "$HOME/google-cloud-sdk/completion.bash.inc"' >> ~/.bashrc
pip install --user google-api-python-client google-auth
