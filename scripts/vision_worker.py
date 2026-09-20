#!/usr/bin/env python3
import base64
import io
import json
import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import torch
from PIL import Image
from transformers import ViTForImageClassification, ViTImageProcessorPil
from transformers.utils import logging as transformers_logging

transformers_logging.set_verbosity_error()


def emit(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: vision_worker.py MODEL_DIRECTORY")
    model_directory = sys.argv[1]
    processor = ViTImageProcessorPil.from_pretrained(model_directory)
    model = ViTForImageClassification.from_pretrained(model_directory).eval()
    torch.set_num_threads(max(1, min(10, os.cpu_count() or 1)))
    emit({"ready": True, "model": model_directory})

    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            encoded_images = request.get("images")
            if not isinstance(request_id, int) or not isinstance(encoded_images, list) or not 1 <= len(encoded_images) <= 14:
                raise ValueError("invalid request")
            images = []
            for encoded in encoded_images:
                if not isinstance(encoded, str) or len(encoded) > 2_000_000:
                    raise ValueError("invalid image payload")
                raw = base64.b64decode(encoded, validate=True)
                if len(raw) > 1_500_000:
                    raise ValueError("image payload too large")
                images.append(Image.open(io.BytesIO(raw)).convert("RGB"))
            inputs = processor(images=images, return_tensors="pt")
            with torch.inference_mode():
                logits = model(**inputs).logits
            probabilities = torch.softmax(logits, dim=-1)
            values, indices = probabilities.topk(2, dim=-1)
            predictions = []
            for row_indices, row_values in zip(indices, values):
                predictions.append({
                    "label": model.config.id2label[int(row_indices[0])],
                    "confidence": float(row_values[0]),
                    "runnerUpLabel": model.config.id2label[int(row_indices[1])],
                    "runnerUpConfidence": float(row_values[1]),
                })
            emit({"id": request_id, "predictions": predictions})
        except Exception as error:
            emit({"id": request_id, "error": f"{type(error).__name__}: {error}"})


if __name__ == "__main__":
    main()
