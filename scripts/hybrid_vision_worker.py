#!/usr/bin/env python3
"""Persistent cvmaj + AutoMajsoul tile-classification worker.

cvmaj supplies the normal 34-class result.  AutoMajsoul overrides it only
when its top class is an explicit red five (5m-, 5p-, or 5s-).
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch import Tensor, nn


CVMAJ_LABELS = [f"{rank}{suit}" for suit in "mps" for rank in range(1, 10)] + [f"{rank}z" for rank in range(1, 8)]
RED_LABELS = {"5m-": "0m", "5p-": "0p", "5s-": "0s"}


class CvMaj(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.pool = nn.MaxPool2d(2, 2)
        self.conv1 = nn.Conv2d(3, 32, 5)
        self.conv2 = nn.Conv2d(32, 64, 5)
        self.conv3 = nn.Conv2d(64, 128, 5)
        self.fc1 = nn.Linear(128, 64)
        self.fc2 = nn.Linear(64, 34)

    def forward(self, value: Tensor) -> Tensor:
        value = self.pool(torch.relu(self.conv1(value)))
        value = self.pool(torch.relu(self.conv2(value)))
        value = torch.relu(self.conv3(value))
        return self.fc2(torch.relu(self.fc1(torch.flatten(value, 1))))


class AutoMajsoul(nn.Module):
    def __init__(self, classes: int) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True), nn.MaxPool2d(2),
            nn.Conv2d(128, 256, 3, padding=1), nn.BatchNorm2d(256), nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(0.3), nn.Linear(256, classes))

    def forward(self, value: Tensor) -> Tensor:
        return self.classifier(self.features(value))


def decode_images(encoded: list[str]) -> tuple[Tensor, Tensor]:
    cvmaj_inputs = []
    red_inputs = []
    for value in encoded:
        image = Image.open(io.BytesIO(base64.b64decode(value))).convert("RGB")
        cvmaj_rgb = np.asarray(image.resize((32, 32))).copy()
        cvmaj_bgr = cvmaj_rgb[:, :, ::-1].copy()
        red_rgb = np.asarray(image.resize((64, 64))).copy()
        cvmaj_inputs.append(torch.from_numpy(cvmaj_bgr).permute(2, 0, 1).float() / 255)
        red_inputs.append(torch.from_numpy(red_rgb).permute(2, 0, 1).float() / 127.5 - 1)
    return torch.stack(cvmaj_inputs), torch.stack(red_inputs)


def ranked(probabilities: Tensor, labels: list[str]) -> list[dict[str, object]]:
    scores, indices = probabilities.topk(2, dim=-1)
    return [
        {
            "label": labels[int(indexes[0])],
            "confidence": float(values[0]),
            "runnerUpLabel": labels[int(indexes[1])],
            "runnerUpConfidence": float(values[1]),
        }
        for values, indexes in zip(scores, indices)
    ]


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: hybrid_vision_worker.py CVMAJ_WEIGHTS AUTOMAJSOUL_WEIGHTS")
    cvmaj_path, auto_path = map(Path, sys.argv[1:])
    if not cvmaj_path.is_file() or not auto_path.is_file():
        raise FileNotFoundError("Hybrid model files are missing; run npm run hybrid-vision:setup")

    cvmaj_checkpoint = torch.load(cvmaj_path, map_location="cpu", weights_only=False)
    cvmaj = CvMaj()
    cvmaj.load_state_dict(cvmaj_checkpoint["state_dict"])
    cvmaj.eval()

    auto_checkpoint = torch.load(auto_path, map_location="cpu", weights_only=False)
    auto_labels = list(auto_checkpoint["classes"])
    auto = AutoMajsoul(len(auto_labels))
    auto.load_state_dict(auto_checkpoint["model_state"])
    auto.eval()

    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            images = request.get("images", [])
            if not isinstance(images, list) or not 0 < len(images) <= 64:
                raise ValueError("images must contain 1 to 64 entries")
            cvmaj_inputs, auto_inputs = decode_images(images)
            with torch.inference_mode():
                normal = ranked(cvmaj(cvmaj_inputs).softmax(-1), CVMAJ_LABELS)
                red = ranked(auto(auto_inputs).softmax(-1), auto_labels)
            predictions = []
            for normal_prediction, red_prediction in zip(normal, red):
                red_label = RED_LABELS.get(str(red_prediction["label"]))
                selected = dict(red_prediction if red_label else normal_prediction)
                if red_label:
                    selected["label"] = red_label
                    runner_up = str(selected["runnerUpLabel"])
                    selected["runnerUpLabel"] = normal_prediction["label"] if runner_up == "x" else RED_LABELS.get(runner_up, runner_up)
                selected.update({
                    "selectedBy": "red-gate" if red_label else "normal",
                    "normalPrediction": normal_prediction,
                    "redPrediction": red_prediction,
                })
                predictions.append(selected)
            print(json.dumps({"id": request.get("id"), "predictions": predictions}), flush=True)
        except Exception as error:  # keep the persistent worker alive after a bad request
            print(json.dumps({"id": request.get("id"), "error": str(error)}), flush=True)


if __name__ == "__main__":
    main()
