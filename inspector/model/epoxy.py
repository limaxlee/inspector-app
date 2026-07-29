import io
import os
import time

import torch
import torchvision.transforms as transforms
from PIL import Image
from torchvision import models

from common.config import SETTINGS
from inspector.model.base import BaseInspector


class EpoxyInspector(BaseInspector):
    """Two-stage epoxy image classifier.

    Stage 1 ("classifier") routes the image to a type. If the type is one of
    E1/E3/PS/M3 the matching stage-2 model produces the final decision;
    otherwise the result is "Unknown".
    """

    name = "epoxy"

    def __init__(self, device: str | None = None):
        super().__init__()
        self.device = torch.device(device or SETTINGS.device)
        self.ckpt_dir = os.path.join(SETTINGS.checkpoint_dir, "epoxy")
        self.classes = ["Good", "Miscaptured", "NG", "Unknown"]
        self.threshold = SETTINGS.threshold
        self.models = {
            "classifier": {
                "checkpoint": self._get_latest_checkpoint("aa-classifier"),
                "model": models.efficientnet_v2_s(weights=None),
            },
            "E1": {
                "checkpoint": self._get_latest_checkpoint("aa-e1"),
                "model": models.efficientnet_v2_s(weights=None),
            },
            "E3": {
                "checkpoint": self._get_latest_checkpoint("aa-e3"),
                "model": models.efficientnet_v2_s(weights=None),
            },
            "PS": {
                "checkpoint": self._get_latest_checkpoint("aa-ps"),
                "model": models.efficientnet_v2_s(weights=None),
            },
            "M3": {
                "checkpoint": self._get_latest_checkpoint("aa-m3"),
                "model": models.efficientnet_v2_s(weights=None),
            },
        }

    def _get_latest_checkpoint(self, prefix: str) -> str:
        matches = sorted(
            os.path.join(self.ckpt_dir, f)
            for f in os.listdir(self.ckpt_dir)
            if f.startswith(prefix)
        )
        if not matches:
            raise FileNotFoundError(
                f"No checkpoint starting with '{prefix}' found in '{self.ckpt_dir}'."
            )
        return matches[-1]

    def load(self):
        """Load every model's weights and run one warmup pass."""
        for name, model_info in self.models.items():
            input_size = self.load_model(name)
            blank = torch.zeros(
                (1, 3, input_size[0], input_size[1]), dtype=torch.float32
            ).to(self.device)
            with torch.no_grad():
                model_info["model"](blank)

    def load_model(self, model_name: str, checkpoint_path: str | None = None):
        if model_name not in self.models:
            raise KeyError(f"Model '{model_name}' is not supported.")

        if checkpoint_path:
            if not os.path.exists(checkpoint_path):
                raise FileNotFoundError(
                    f"Checkpoint file '{checkpoint_path}' does not exist."
                )
            self.models[model_name]["checkpoint"] = checkpoint_path

        info = self.models[model_name]
        checkpoint = torch.load(
            info["checkpoint"], map_location=self.device, weights_only=False
        )
        info["classes"] = checkpoint["class_names"]
        input_size = checkpoint["input_size"]
        info["class_map"] = {i: v for i, v in enumerate(info["classes"])}
        info["transforms"] = transforms.Compose([
            transforms.Resize(input_size),
            transforms.ToTensor(),
            transforms.Normalize(mean=checkpoint["mean"], std=checkpoint["std"]),
        ])
        model = info["model"]
        model.classifier[1] = torch.nn.Linear(
            model.classifier[1].in_features, len(info["classes"])
        )
        model.load_state_dict(checkpoint["weights"])
        model.to(self.device)
        model.eval()

        return input_size

    def _preprocess(self, model_name: str, input_image):
        if isinstance(input_image, str):
            image = Image.open(input_image).convert("RGB")
        elif isinstance(input_image, bytes):
            image = Image.open(io.BytesIO(input_image)).convert("RGB")
        else:
            raise TypeError("Input must be bytes or a path to an image.")

        return self.models[model_name]["transforms"](image).unsqueeze(0).to(self.device)

    def _predict(self, model_name: str, input_image):
        transformed = self._preprocess(model_name, input_image)
        model = self.models[model_name]["model"]

        captured = {}

        def _capture_features(_module, inputs):
            # inputs[0] is the flattened [batch, 1280] feature vector
            captured["feature_vector"] = inputs[0].detach()

        handle = model.classifier.register_forward_pre_hook(_capture_features)
        try:
            with torch.no_grad():
                outputs = model(transformed)
                probs = torch.nn.functional.softmax(outputs, dim=1)
                confidence, prediction = torch.max(probs, 1)
                prediction = self.models[model_name]["class_map"][prediction.item()]
                confidence = round(confidence.item() * 100, 2)
        finally:
            handle.remove()

        feature_vector = captured["feature_vector"].squeeze(0).cpu().tolist()
        return prediction, confidence, feature_vector

    def predict(self, input_image):
        t0 = time.perf_counter()
        stages = []

        # Stage 1: classifier
        inference_model = "classifier"
        prediction, confidence, feature_vector = self._predict(inference_model, input_image)
        stages.append({
            "inference_model": inference_model,
            "version": self.get_version(inference_model),
            "decision": prediction,
            "confidence": confidence,
            "feature_vector": feature_vector,
        })

        # Stage 2: type-specific model, only if the classifier routed to one
        if prediction in ("E1", "E3", "PS", "M3"):
            inference_model = prediction
            prediction, confidence, feature_vector = self._predict(inference_model, input_image)
            stages.append({
                "inference_model": inference_model,
                "version": self.get_version(inference_model),
                "decision": prediction,
                "confidence": confidence,
                "feature_vector": feature_vector,
            })
            final_version = self.get_version(inference_model)
        else:
            inference_model = f"unknown({prediction})"
            prediction = "Unknown"
            confidence = 0.0
            final_version = None
            # feature_vector stays as the classifier's (the only model that ran)

        elapsed_time = round(time.perf_counter() - t0, 4)

        return {
            "ai_model": self.name,
            "inference_model": inference_model,
            "version": final_version,
            "classes": self.classes,
            "decision": prediction,
            "confidence": confidence,
            "feature_vector": feature_vector,
            "threshold": self.threshold,
            "elapsed_time": elapsed_time,
            "stages": stages,
        }

    def set_threshold(self, value: float, key: str | None = None):
        # Epoxy has a single image-level threshold, so `key` is accepted (for a
        # uniform interface with the per-class detectors) but unused.
        if value < 0.0 or value > 100.0:
            raise ValueError("Threshold must be between 0 and 100.")
        self.threshold = value

    def get_threshold(self, key: str | None = None) -> float:
        return self.threshold

    def get_models_info(self):
        return [
            {"ai_model": self.name, "model_name": name, "version": self.get_version(name)}
            for name in self.models
        ]

    def get_version(self, model_name: str) -> str:
        return self.models[model_name]["checkpoint"].split("-")[-1].replace(".pth", "")

    def release(self):
        for model_info in self.models.values():
            model_info.pop("model", None)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
