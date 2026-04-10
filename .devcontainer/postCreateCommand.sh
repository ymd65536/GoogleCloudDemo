# bin/bash
curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts
echo 'source "$HOME/google-cloud-sdk/path.zsh.inc"' >> ~/.zshrc
echo 'source "$HOME/google-cloud-sdk/completion.zsh.inc"' >> ~/.zshrc
echo 'source "$HOME/google-cloud-sdk/path.bash.inc"' >> ~/.bashrc
echo 'source "$HOME/google-cloud-sdk/completion.bash.inc"' >> ~/.bashrc
echo 'export PS1="$ "' >> ~/.bashrc

# install pip for system python if missing
/usr/bin/python3 -m pip --version 2>/dev/null || curl -sS https://bootstrap.pypa.io/get-pip.py | /usr/bin/python3 - --break-system-packages

# google-cloud-python
pip install --user google-cloud-artifact-registry

# google-api-python-client
pip install --user google-api-python-client google-auth
