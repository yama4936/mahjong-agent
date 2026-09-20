#!/usr/bin/env bash
set -euo pipefail

runtime_dir=".runtime/vision-venv"
model_dir=".runtime/mahjong-vision"
revision="712950faa97b0b0f2a23ae68f7352c9116a91285"

if [[ ! -x "$runtime_dir/bin/python" ]]; then
  uv venv "$runtime_dir" --python 3.12
fi
uv pip install --python "$runtime_dir/bin/python" --index-url https://download.pytorch.org/whl/cpu torch
uv pip install --python "$runtime_dir/bin/python" transformers pillow safetensors
"$runtime_dir/bin/python" - "$model_dir" "$revision" <<'PY'
import sys
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="krmin/mahjong_vision",
    revision=sys.argv[2],
    allow_patterns=["vision_transformer_local/*"],
    local_dir=sys.argv[1],
)
PY
