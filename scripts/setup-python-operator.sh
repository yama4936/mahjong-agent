#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="$project_dir/.runtime/python-auto-venv"
uv venv --clear "$runtime_dir"
uv pip install --python "$runtime_dir/bin/python" -r "$project_dir/python/requirements.txt"
echo "Python operator ready: $runtime_dir/bin/python"
