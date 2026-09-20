#!/usr/bin/env python3
"""Compare tile classifiers on the exact same labeled crops.

This benchmark deliberately separates same-session live crops from the public
pjura dataset.  Softmax scores are recorded for diagnostics only; they are not
treated as calibrated probabilities or an Auto-operation certificate.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from torch import Tensor, nn
from transformers import ViTForImageClassification, ViTImageProcessorPil


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "artifacts/recognition-ablation/normalized-live"
OUTPUT_DIR = ROOT / "artifacts/model-comparison"
VISION_DIR = ROOT / ".runtime/mahjong-vision/vision_transformer_local"
CVMAJ_WEIGHTS = ROOT / ".runtime/model-comparison/cvmaj/pretrained.tar"
AUTOMAJSOUL_WEIGHTS = ROOT / ".runtime/model-comparison/AutoMajsoul/Android/mj_cnn/checkpoints/best_model.pt"
HASE_WEIGHTS = ROOT / ".runtime/model-comparison/hase-models/classifier-resnet50.pt"
LOCAL_CNN_WEIGHTS = ROOT / "artifacts/recognition-ablation/cnn37-experiment.pt"

# Visually verified against the original-resolution crops during this run.  The
# newer fed619da 2s sample is a real 2s and is intentionally not listed here.
GROUND_TRUTH_CORRECTIONS = {
    "2s__train_mu9cs1s9_08.png": "3s",
    "2s__train_mu9cs3j2_08.png": "3s",
    "2s__train_mu9cs59w_07.png": "3s",
    "2s__train_mu9cs71c_08.png": "3s",
    "2s__train_mu9cs8u1_08.png": "3s",
    "2s__train_mu9csakj_08.png": "3s",
}

HONOR_TO_LOCAL = {"1z": "E", "2z": "S", "3z": "W", "4z": "N", "5z": "P", "6z": "F", "7z": "C"}
PJURA_TO_LOCAL = {
    "ew": "E", "sw": "S", "ww": "W", "nw": "N", "wd": "P", "gd": "F", "rd": "C",
}


def canonical(label: str) -> str:
    if label in HONOR_TO_LOCAL:
        return HONOR_TO_LOCAL[label]
    if label in PJURA_TO_LOCAL:
        return PJURA_TO_LOCAL[label]
    if label.endswith("-") and label[:2] in {"5m", "5p", "5s"}:
        return "0" + label[1]
    if len(label) == 2 and label[0].isdigit() and label[1] == "b":
        return label[0] + "s"
    if len(label) == 2 and label[0].isdigit() and label[1] == "n":
        return label[0] + "m"
    return label


def image_tensor(path: Path, size: tuple[int, int], *, bgr: bool = False) -> Tensor:
    image = Image.open(path).convert("RGB").resize(size)
    array = np.asarray(image).copy()
    if bgr:
        array = array[:, :, ::-1].copy()
    return torch.from_numpy(array).permute(2, 0, 1).float()


class CvMaj(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.pool = nn.MaxPool2d(2, 2)
        self.conv1 = nn.Conv2d(3, 32, 5)
        self.conv2 = nn.Conv2d(32, 64, 5)
        self.conv3 = nn.Conv2d(64, 128, 5)
        self.fc1 = nn.Linear(128, 64)
        self.fc2 = nn.Linear(64, 34)

    def forward(self, x: Tensor) -> Tensor:
        x = self.pool(torch.relu(self.conv1(x)))
        x = self.pool(torch.relu(self.conv2(x)))
        x = torch.relu(self.conv3(x))
        x = torch.flatten(x, 1)
        return self.fc2(torch.relu(self.fc1(x)))


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

    def forward(self, x: Tensor) -> Tensor:
        return self.classifier(self.features(x))


class LocalCnn(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.model = nn.Sequential(
            nn.Conv2d(3, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Flatten(), nn.Linear(32 * 12 * 8, 128), nn.ReLU(), nn.Dropout(0.15), nn.Linear(128, 37),
        )

    def forward(self, x: Tensor) -> Tensor:
        return self.model(x)


class Bottleneck(nn.Module):
    expansion = 4

    def __init__(self, inplanes: int, planes: int, stride: int = 1, downsample: nn.Module | None = None) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(inplanes, planes, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, 3, stride=stride, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(planes)
        self.conv3 = nn.Conv2d(planes, planes * 4, 1, bias=False)
        self.bn3 = nn.BatchNorm2d(planes * 4)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x: Tensor) -> Tensor:
        identity = x
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.relu(self.bn2(self.conv2(out)))
        out = self.bn3(self.conv3(out))
        if self.downsample is not None:
            identity = self.downsample(x)
        return self.relu(out + identity)


class ResNet50(nn.Module):
    """Torchvision/timm-compatible ResNet-50 without importing torchvision."""

    def __init__(self, classes: int) -> None:
        super().__init__()
        self.inplanes = 64
        self.conv1 = nn.Conv2d(3, 64, 7, stride=2, padding=3, bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(3, stride=2, padding=1)
        self.layer1 = self._layer(64, 3)
        self.layer2 = self._layer(128, 4, stride=2)
        self.layer3 = self._layer(256, 6, stride=2)
        self.layer4 = self._layer(512, 3, stride=2)
        self.global_pool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(512 * Bottleneck.expansion, classes)

    def _layer(self, planes: int, blocks: int, stride: int = 1) -> nn.Sequential:
        downsample = None
        if stride != 1 or self.inplanes != planes * Bottleneck.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * Bottleneck.expansion, 1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * Bottleneck.expansion),
            )
        layers = [Bottleneck(self.inplanes, planes, stride, downsample)]
        self.inplanes = planes * Bottleneck.expansion
        layers.extend(Bottleneck(self.inplanes, planes) for _ in range(1, blocks))
        return nn.Sequential(*layers)

    def forward(self, x: Tensor) -> Tensor:
        x = self.maxpool(self.relu(self.bn1(self.conv1(x))))
        x = self.layer4(self.layer3(self.layer2(self.layer1(x))))
        return self.fc(torch.flatten(self.global_pool(x), 1))


def batched_predict(model: nn.Module, inputs: Tensor, labels: list[str], batch_size: int = 16) -> tuple[list[str], list[float], float]:
    model.eval()
    # Warm up once so import/setup time is not charged to per-image inference.
    with torch.inference_mode():
        model(inputs[:1])
    started = time.perf_counter()
    probabilities = []
    with torch.inference_mode():
        for batch in inputs.split(batch_size):
            probabilities.append(model(batch).softmax(-1))
    elapsed = time.perf_counter() - started
    probs = torch.cat(probabilities)
    scores, indices = probs.max(-1)
    return [canonical(labels[int(i)]) for i in indices], [float(x) for x in scores], elapsed


def predict_cvmaj(paths: list[Path]) -> tuple[list[str], list[float], float, dict]:
    checkpoint = torch.load(CVMAJ_WEIGHTS, map_location="cpu", weights_only=False)
    model = CvMaj()
    model.load_state_dict(checkpoint["state_dict"])
    labels = [f"{n}{s}" for s in "mps" for n in range(1, 10)] + [f"{n}z" for n in range(1, 8)]
    inputs = torch.stack([image_tensor(path, (32, 32), bgr=True) / 255 for path in paths])
    predicted, scores, elapsed = batched_predict(model, inputs, labels, batch_size=32)
    return predicted, scores, elapsed, {"revision": "6e2ca242b73b89adb52f9d374513b7178056278a", "classes": 34}


def predict_automajsoul(paths: list[Path]) -> tuple[list[str], list[float], float, dict]:
    checkpoint = torch.load(AUTOMAJSOUL_WEIGHTS, map_location="cpu", weights_only=False)
    labels = checkpoint["classes"]
    model = AutoMajsoul(len(labels))
    model.load_state_dict(checkpoint["model_state"])
    inputs = torch.stack([image_tensor(path, (64, 64)) / 127.5 - 1 for path in paths])
    predicted, scores, elapsed = batched_predict(model, inputs, labels, batch_size=32)
    return predicted, scores, elapsed, {"revision": "1ea1f065fd31800495819d29eb6bb66458c1700a", "classes": len(labels)}


def predict_hase(paths: list[Path], preprocessing: str = "imagenet") -> tuple[list[str], list[float], float, dict]:
    checkpoint = torch.load(HASE_WEIGHTS, map_location="cpu", weights_only=False)
    labels = checkpoint["classes"]
    model = ResNet50(len(labels))
    model.load_state_dict(checkpoint["model"])
    inputs = torch.stack([image_tensor(path, (checkpoint["image_size"], checkpoint["image_size"])) / 255 for path in paths])
    if preprocessing == "imagenet":
        mean = torch.tensor([0.485, 0.456, 0.406])[None, :, None, None]
        std = torch.tensor([0.229, 0.224, 0.225])[None, :, None, None]
        inputs = (inputs - mean) / std
    elif preprocessing == "raw-255":
        inputs = inputs * 255
    elif preprocessing != "zero-one":
        raise ValueError(f"unknown HaseLab preprocessing: {preprocessing}")
    predicted, scores, elapsed = batched_predict(model, inputs, labels, batch_size=16)
    metadata = {
        "revision": "db01725eaa2b40c160282b0f582d22f4c0333150",
        "classes": len(labels),
        "checkpointValAccuracy": checkpoint.get("val_accuracy"),
        "checkpointValMacroAccuracy": checkpoint.get("val_macro_accuracy"),
        "preprocessing": preprocessing,
    }
    return predicted, scores, elapsed, metadata


def predict_pjura(paths: list[Path]) -> tuple[list[str], list[float], float, dict]:
    processor = ViTImageProcessorPil.from_pretrained(VISION_DIR)
    model = ViTForImageClassification.from_pretrained(VISION_DIR).eval()
    images = [Image.open(path).convert("RGB") for path in paths]
    with torch.inference_mode():
        model(**processor(images=images[:1], return_tensors="pt"))
    started = time.perf_counter()
    probabilities = []
    with torch.inference_mode():
        for offset in range(0, len(images), 14):
            inputs = processor(images=images[offset:offset + 14], return_tensors="pt")
            probabilities.append(model(**inputs).logits.softmax(-1))
    elapsed = time.perf_counter() - started
    probs = torch.cat(probabilities)
    scores, indices = probs.max(-1)
    labels = [model.config.id2label[int(i)] for i in indices]
    return [canonical(x) for x in labels], [float(x) for x in scores], elapsed, {
        "revision": "712950faa97b0b0f2a23ae68f7352c9116a91285", "classes": 34,
    }


def predict_local_cnn(paths: list[Path]) -> tuple[list[str], list[float], float, dict]:
    checkpoint = torch.load(LOCAL_CNN_WEIGHTS, map_location="cpu", weights_only=False)
    model = LocalCnn()
    model.model.load_state_dict(checkpoint["model"])
    inputs = torch.stack([image_tensor(path, (32, 48)) / 255 for path in paths])
    predicted, scores, elapsed = batched_predict(model, inputs, checkpoint["classes"], batch_size=32)
    return predicted, scores, elapsed, {
        "classes": len(checkpoint["classes"]), "trainedClasses": checkpoint["trainedClasses"],
        "warning": "Trained on four of the six live source frames; only held-2-frames metrics are valid.",
    }


def summarize(name: str, rows: list[dict], predictions: list[str], scores: list[float], elapsed: float, metadata: dict) -> dict:
    detailed = []
    frames: dict[str, list[bool]] = defaultdict(list)
    for row, predicted, score in zip(rows, predictions, scores):
        correct = predicted == row["label"]
        frame = row.get("sourceScreenshot") or "public"
        frames[frame].append(correct)
        detailed.append({
            "crop": row["crop"], "expected": row["label"], "predicted": predicted,
            "score": score, "correct": correct, "sourceScreenshot": row.get("sourceScreenshot"),
        })
    errors = Counter((r["expected"], r["predicted"]) for r in detailed if not r["correct"])
    correct = sum(r["correct"] for r in detailed)
    non_red = [r for r in detailed if r["expected"] not in {"0m", "0p", "0s"}]
    red = [r for r in detailed if r["expected"] in {"0m", "0p", "0s"}]
    complete_frames = [values for values in frames.values() if len(values) == 14]
    return {
        "model": name,
        "total": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows) if rows else None,
        "nonRedCorrect": sum(r["correct"] for r in non_red),
        "nonRedTotal": len(non_red),
        "redCorrect": sum(r["correct"] for r in red),
        "redTotal": len(red),
        "completeFrames": len(complete_frames),
        "completeFramesAllCorrect": sum(all(values) for values in complete_frames),
        "meanTop1Score": statistics.fmean(scores) if scores else None,
        "elapsedSeconds": elapsed,
        "meanMillisecondsPerCrop": elapsed * 1000 / len(rows) if rows else None,
        "commonErrors": [{"expected": a, "predicted": b, "count": n} for (a, b), n in errors.most_common(10)],
        "metadata": metadata,
        "rows": detailed,
    }


def public_rows() -> list[dict]:
    report = json.loads((ROOT / "artifacts/recognition-ablation/report.json").read_text())
    return [
        {"crop": row["file"], "label": row["label"], "path": ROOT / "templates/bootstrap" / row["file"]}
        for row in report["results"]["baseline"]["rows"]
    ]


def existing_template_result(dataset: str, held_groups: set[str] | None = None) -> dict:
    """Import the current face-normalized template result from its LOFO benchmark."""
    if dataset == "public":
        source = json.loads((ROOT / "artifacts/recognition-ablation/report.json").read_text())["results"]["normalized"]
        rows = [dict(row) for row in source["rows"]]
        total = source["total"]
        correct = source["correct"]
        elapsed = source["meanMs"] * total / 1000
        frames = 0
        frame_correct = 0
    else:
        source = json.loads((ROOT / "artifacts/recognition-ablation/live-report.json").read_text())["summaries"]["normalized"]
        rows = [dict(row) for row in source["rows"]]
        if held_groups is not None:
            rows = [row for row in rows if row.get("sourceScreenshot") in held_groups]
        for row in rows:
            row["label"] = GROUND_TRUTH_CORRECTIONS.get(row["crop"], row["label"])
        total = len(rows)
        correct = sum(row["label"] == row["predicted"] for row in rows)
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row["sourceScreenshot"]].append(row)
        complete = [values for values in grouped.values() if len(values) == 14]
        frames = len(complete)
        frame_correct = sum(all(row["label"] == row["predicted"] for row in values) for values in complete)
        elapsed = None
    errors = Counter((row["label"], row["predicted"]) for row in rows if row["label"] != row["predicted"])
    non_red = [row for row in rows if row["label"] not in {"0m", "0p", "0s"}]
    red = [row for row in rows if row["label"] in {"0m", "0p", "0s"}]
    return {
        "model": "current-template-face-lofo",
        "total": total,
        "correct": correct,
        "accuracy": correct / total,
        "nonRedCorrect": sum(row["label"] == row["predicted"] for row in non_red),
        "nonRedTotal": len(non_red),
        "redCorrect": sum(row["label"] == row["predicted"] for row in red),
        "redTotal": len(red),
        "completeFrames": frames,
        "completeFramesAllCorrect": frame_correct,
        "meanTop1Score": statistics.fmean(row["score"] for row in rows),
        "elapsedSeconds": elapsed,
        "meanMillisecondsPerCrop": None if elapsed is None else elapsed * 1000 / total,
        "commonErrors": [{"expected": a, "predicted": b, "count": n} for (a, b), n in errors.most_common(10)],
        "metadata": {
            "strategy": "face-normalized template matching",
            "split": "leave-one-source-frame-out" if dataset == "live" else "fixed public holdout",
            "sourceReport": "artifacts/recognition-ablation/live-report.json" if dataset == "live" else "artifacts/recognition-ablation/report.json",
        },
        "rows": rows,
    }


def run_set(name: str, rows: list[dict], include_local: bool) -> dict:
    paths = [Path(row.get("path") or DATA_DIR / row["crop"]) for row in rows]
    runners = {
        "pjura-vit34": predict_pjura,
        "hase-resnet50-39": predict_hase,
        "cvmaj-cnn34": predict_cvmaj,
        "automajsoul-tilenet38": predict_automajsoul,
    }
    if include_local:
        runners["local-cnn37"] = predict_local_cnn
    results = {}
    for model_name, runner in runners.items():
        print(json.dumps({"dataset": name, "running": model_name}), flush=True)
        predictions, scores, elapsed, metadata = runner(paths)
        results[model_name] = summarize(model_name, rows, predictions, scores, elapsed, metadata)
    return results


def add_red_gate_ensemble(results: dict, rows: list[dict]) -> None:
    """Use AutoMajsoul only for an explicit red-five prediction, else cvmaj."""
    cvmaj = results["cvmaj-cnn34"]
    auto = results["automajsoul-tilenet38"]
    predicted = []
    scores = []
    for cv_row, auto_row in zip(cvmaj["rows"], auto["rows"]):
        chosen = auto_row if auto_row["predicted"] in {"0m", "0p", "0s"} else cv_row
        predicted.append(chosen["predicted"])
        scores.append(chosen["score"])
    results["cvmaj+automajsoul-red-gate"] = summarize(
        "cvmaj+automajsoul-red-gate", rows, predicted, scores,
        cvmaj["elapsedSeconds"] + auto["elapsedSeconds"],
        {"rule": "AutoMajsoul prediction when it is an explicit red five; otherwise cvmaj"},
    )


def markdown(report: dict) -> str:
    lines = [
        "# Mahjong tile recognition model comparison", "",
        f"Generated: {report['evaluatedAt']}", "",
        "Softmax scores are uncalibrated. No result is an Auto-operation certificate.", "",
    ]
    for dataset_name, section in report["datasets"].items():
        lines.extend([f"## {dataset_name}", "", "| Model | Exact | Non-red exact | Red exact | Complete frames | ms/crop |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
        for value in sorted(section.values(), key=lambda x: x["accuracy"], reverse=True):
            frames = f"{value['completeFramesAllCorrect']}/{value['completeFrames']}" if value["completeFrames"] else "—"
            milliseconds = "—" if value["meanMillisecondsPerCrop"] is None else f"{value['meanMillisecondsPerCrop']:.1f}"
            non_red = f"{value['nonRedCorrect']}/{value['nonRedTotal']}" if value["nonRedTotal"] else "—"
            red = f"{value['redCorrect']}/{value['redTotal']}" if value["redTotal"] else "—"
            lines.append(f"| {value['model']} | {value['correct']}/{value['total']} ({value['accuracy']:.1%}) | {non_red} | {red} | {frames} | {milliseconds} |")
        lines.append("")
    lines.extend(["## Limitations", ""] + [f"- {x}" for x in report["limitations"]] + [""])
    return "\n".join(lines)


def main() -> None:
    torch.set_num_threads(max(1, min(10, torch.get_num_threads())))
    manifest = json.loads((DATA_DIR / "manifest.json").read_text())
    live = [dict(row) for row in manifest if row.get("sourceScreenshot")]
    for row in live:
        row["label"] = GROUND_TRUTH_CORRECTIONS.get(row["crop"], row["label"])
    groups = sorted({row["sourceScreenshot"] for row in live})
    held_groups = set(groups[-2:])
    held = [row for row in live if row["sourceScreenshot"] in held_groups]
    live_dataset_name = f"live-all-{len(groups)}-correlated-frames"
    live_results = run_set(live_dataset_name, live, include_local=False)
    held_results = run_set("live-held-2-frames", held, include_local=True)
    public = public_rows()
    public_results = run_set("pjura-public-holdout", public, include_local=False)
    add_red_gate_ensemble(live_results, live)
    add_red_gate_ensemble(held_results, held)
    add_red_gate_ensemble(public_results, public)
    live_results["current-template-face-lofo"] = existing_template_result("live")
    held_results["current-template-face-lofo"] = existing_template_result("live", held_groups)
    public_results["current-template-face-lofo"] = existing_template_result("public")
    report = {
        "evaluatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "datasets": {
            live_dataset_name: live_results,
            "live-held-2-frames": held_results,
            "pjura-public-holdout": public_results,
        },
        "heldSourceFrames": sorted(held_groups),
        "groundTruthCorrections": GROUND_TRUTH_CORRECTIONS,
        "limitations": [
            f"The live set contains only {len(live)} crops from {len(groups)} correlated frames in one session and does not cover all 37 classes.",
            "The only observed red five is red sou; red man and red pin are absent.",
            "Six legacy crops labeled 2s were visually verified as 3s and corrected only in this comparison report; source training manifests were not changed.",
            "The public holdout comes from pjura/mahjong_souls_tiles and may overlap pjura ViT training or augmentation lineage.",
            "The local CNN is reported only on its two held source frames; the remaining live source frames were training data.",
            "HaseLab preprocessing is inferred from the declared timm/resnet50 architecture because the model card does not publish transforms.",
            "Latency is CPU batch throughput on this machine, not single-frame end-to-end screen recognition latency.",
        ],
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (OUTPUT_DIR / "comparison.md").write_text(markdown(report))
    print(markdown(report), flush=True)


if __name__ == "__main__":
    main()
