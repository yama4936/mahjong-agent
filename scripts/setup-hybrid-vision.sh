#!/usr/bin/env bash
set -euo pipefail

runtime_dir=".runtime/vision-venv"
model_dir=".runtime/hybrid-vision"
cvmaj_sha="f6e618b3448cedf990be71eb47929d1d0426f6cfc2b5c46c2d11a9df47f16770"
auto_sha="839fe5848cfeae661e5a95860e176739883215f9d13922963b8e21fc8770048c"

if [[ ! -x "$runtime_dir/bin/python" ]]; then
  uv venv "$runtime_dir" --python 3.12
fi
uv pip install --python "$runtime_dir/bin/python" --index-url https://download.pytorch.org/whl/cpu torch
uv pip install --python "$runtime_dir/bin/python" pillow numpy
mkdir -p "$model_dir"

download() {
  local url="$1"
  local output="$2"
  local expected="$3"
  if [[ ! -f "$output" ]] || [[ "$(sha256sum "$output" | cut -d' ' -f1)" != "$expected" ]]; then
    curl --fail --location --silent --show-error "$url" --output "$output"
  fi
  echo "$expected  $output" | sha256sum --check --status
}

download \
  "https://raw.githubusercontent.com/xdedss/cvmaj/6e2ca242b73b89adb52f9d374513b7178056278a/pretrained.tar" \
  "$model_dir/cvmaj-pretrained.tar" "$cvmaj_sha"
download \
  "https://raw.githubusercontent.com/yuhao7370/AutoMajsoul/1ea1f065fd31800495819d29eb6bb66458c1700a/Android/mj_cnn/checkpoints/best_model.pt" \
  "$model_dir/automajsoul-best-model.pt" "$auto_sha"

echo "Hybrid vision models are ready in $model_dir"
