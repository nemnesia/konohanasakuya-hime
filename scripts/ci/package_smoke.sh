#!/bin/bash

set -ex

wheel_directory=$(mktemp -d)
venv_directory=$(mktemp -d)
trap 'rm -rf "$wheel_directory" "$venv_directory"' EXIT

python3 -m build --wheel --outdir "$wheel_directory" .
python3 -m venv "$venv_directory"
"$venv_directory/bin/python" -m pip install --upgrade pip
"$venv_directory/bin/python" -m pip install "$wheel_directory"/symbol_sakuya-*.whl
"$venv_directory/bin/python" -m sakuya --help
