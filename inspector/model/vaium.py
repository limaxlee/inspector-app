import os
import threading
import time

import cv2
import numpy as np
import torch
from torchvision.ops import roi_align

from chip_detector.models.yolo import Model
from chip_detector.utils.augmentations import letterbox
from chip_detector.utils.general import check_img_size, non_max_suppression
from chip_detector.utils.torch_utils import select_device

from common.config import SETTINGS
from common.constants import ROOT_DIR
from inspector.model.base import BaseInspector

lock = threading.Lock()


class VaiumDetector(BaseInspector):
    """YOLOv5 chip/vaium defect detector with per-box feature extraction."""

    name = "vaium"
    version = "v1"

    def __init__(self):
        super().__init__()
        # Hyperparameters
        self._score_thresholds = {
            "Good": 70.0,
            "Pocket": 70.0,
            "ChipHalf": 60.0,
            "PocketHalf": 60.0,
            "Popup": 70.0,
            "NG": 70.0,
            "Boundary": 20.0,
            "Space": 101.0
        }
        self.default_threshold = 0.20
        self.conf_threshold = 0.20
        self.iou_threshold = 0.50
        self.max_detection = 10
        self.yellow_threshold = 3.0
        self.dark_threshold = 60.0

        self.ckpt_dir = os.path.join(SETTINGS.checkpoint_dir, "vaium")

        # GPU configs — the device is resolved in load(), not here, so that
        # importing this module never claims a GPU on its own.
        self.device = None
        self.half = False

        # Model params
        self.model = None
        self.stride = 32
        self.imgsz = 1280
        self.names = None

        # Feature-extraction params
        # "Good" is the normal class; everything else is a defect type.
        self.normal_class = "Good"
        # Which detection level to pull per-box features from. 0 == P3 (stride 8,
        # highest resolution) -> best for small defects, and a single level keeps
        # every object vector the same length (required for one Milvus vector field).
        self.roi_level = 0
        self.roi_output_size = 7
        # Whether to also embed "Good" boxes that co-occur inside a defect image.
        # They are useful negatives; set False to store defect objects only.
        self.embed_good_boxes = True
        # Captured neck feature maps [P3, P4, ... deepest]; filled by the pre-hook.
        self._feature_maps = None

    def _resolve_device(self):
        # gpu_util.setup_one_gpu() picks and pins a free GPU; only call it when a
        # GPU is actually wanted, otherwise honour whatever config.yaml asked for.
        configured = str(SETTINGS.device).strip().lower()
        if configured in ("auto", "cuda", "gpu") and torch.cuda.is_available():
            from chip_detector import gpu_util
            return gpu_util.setup_one_gpu()
        if configured in ("auto", "gpu"):
            return "cpu"
        return configured

    def load(self):
        self.device = select_device(self._resolve_device())
        self.half = self.device.type != "cpu"  # half precision only supported on CUDA

        # Paths — chip_detector is vendored at the repo root, not next to this file.
        cfg_dir = os.path.join(ROOT_DIR, "chip_detector", "models")
        best_model = os.path.join(self.ckpt_dir, "model.pt")
        if not os.path.isfile(best_model):
            raise FileNotFoundError(f"Vaium checkpoint '{best_model}' does not exist.")

        # Model configs
        model_sizes = ["nano", "small", "medium", "large", "xlarge"]
        model_configs = {}
        for size in model_sizes:
            model_configs[size] = os.path.abspath(
                os.path.join(cfg_dir, f"yolov5{size[0]}.yaml"))
            model_configs[f"{size}-high"] = os.path.abspath(
                os.path.join(cfg_dir, f"yolov5{size[0]}6.yaml"))

        ckpt = torch.load(best_model, map_location=self.device)
        self.imgsz = 1280 if ckpt["model_size"].endswith("high") else 640
        self.model = Model(model_configs[ckpt["model_size"]], ch=3, nc=ckpt["num_classes"])
        self.model.to(self.device)
        self.model.load_state_dict(ckpt["model"])
        self.stride = int(self.model.stride.max())
        self.imgsz = check_img_size(self.imgsz, s=self.stride)
        self.names = ckpt["class_names"]

        # Register a forward pre-hook on Detect to grab the neck feature maps
        # (P3/P4/P5...) the instant before Detect overwrites them with its convs.
        detect_layer = self.model.model[-1]
        detect_layer.register_forward_pre_hook(self._capture_features)

        # run once
        blank_image = torch.zeros(1, 3, self.imgsz, self.imgsz).to(self.device).type_as(
            next(self.model.parameters()))
        self.model.eval()
        self.model(blank_image)

        if self.device.type != "cpu":
            self.model.half()  # to FP16

    # ------------------------------------------------------------------ #
    # Feature extraction
    # ------------------------------------------------------------------ #
    def _capture_features(self, module, inputs):
        # inputs[0] is the list of neck feature maps passed into Detect.forward,
        # ordered by stride (P3, P4, P5[, P6]). Detect mutates the list in place,
        # so we detach references here, before that happens.
        feats = inputs[0]
        self._feature_maps = [f.detach() for f in feats]

    def _extract_global_embedding(self):
        # Global descriptor = GAP of the deepest (most semantic) feature map.
        if not self._feature_maps:
            return None
        deep = self._feature_maps[-1].float()  # [1, C, h, w]
        return deep.mean(dim=(2, 3)).squeeze(0).cpu().numpy().tolist()

    def _extract_box_embeddings(self, boxes_xyxy_letterbox):
        # boxes_xyxy_letterbox: [K, 4] xyxy in the LETTERBOXED input coordinate
        # frame (same frame the feature maps live in), NOT original-image coords.
        if not self._feature_maps or boxes_xyxy_letterbox.shape[0] == 0:
            return None

        feat = self._feature_maps[self.roi_level].float()  # [1, C, H, W]
        spatial_scale = 1.0 / float(self.model.stride[self.roi_level])

        boxes = boxes_xyxy_letterbox.to(device=feat.device, dtype=feat.dtype)
        batch_idx = torch.zeros((boxes.shape[0], 1), device=feat.device, dtype=feat.dtype)
        rois = torch.cat([batch_idx, boxes], dim=1)  # [K, 5]

        pooled = roi_align(
            feat, rois,
            output_size=(self.roi_output_size, self.roi_output_size),
            spatial_scale=spatial_scale,
            sampling_ratio=2,
            aligned=True
        )  # [K, C, k, k]
        return pooled.mean(dim=(2, 3)).cpu().numpy()  # [K, C]

    @torch.no_grad()
    def predict(self, image_bytes: bytes):
        with lock:
            start = time.perf_counter()
            try:
                # Preprocess
                im0 = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), -1)  # BGR
                if im0 is None:
                    raise ValueError("Could not decode the uploaded image.")
                if len(im0.shape) == 2:  # Grayscale
                    im0 = cv2.cvtColor(im0, cv2.COLOR_GRAY2BGR)
                if im0.shape[2] == 4:  # Remove alpha channel
                    im0 = im0[:, :, :3]

                filter_result = self.is_yellow_or_dark(im0)
                if filter_result:
                    # NOTE: yellow/dark images are rejected BEFORE the network runs,
                    # so no embedding is produced for them. If you need embeddings for
                    # these too, run the model here instead of short-circuiting.
                    return self._format_filtered(filter_result, time.perf_counter() - start)

                gn = torch.tensor(im0.shape, device=self.device)[[1, 0, 1, 0]]
                stride = int(self.model.stride.max())  # model stride
                img = letterbox(im0, self.imgsz, stride=stride)[0]

                # Convert
                img = img[:, :, ::-1].transpose(2, 0, 1)  # BGR to RGB
                img = np.ascontiguousarray(img)

                img = torch.from_numpy(img).to(self.device)
                img = img.half() if self.half else img.float()  # uint8 to fp16/32
                img /= 255.0  # 0 - 255 to 0.0 - 1.0
                if img.ndimension() == 3:
                    img = img.unsqueeze(0)

                # Inference (the pre-hook populates self._feature_maps during this call)
                self._feature_maps = None
                prediction = self.model(img, augment=False)[0]

                # Apply NMS
                prediction = non_max_suppression(prediction,
                                                 conf_thres=self.conf_threshold,
                                                 iou_thres=self.iou_threshold,
                                                 multi_label=False,
                                                 max_det=self.max_detection)

                result = self.postprocess(prediction, im0.shape, img.shape, gn)
                result["elapsed_time"] = round(time.perf_counter() - start, 4)
                return result
            except Exception as ex:
                raise RuntimeError(ex)

    def is_yellow_or_dark(self, cv_image):
        hsv = cv2.cvtColor(cv_image, cv2.COLOR_BGR2HSV)
        mask_yellow = cv2.inRange(hsv, np.array([10, 50, 50]), np.array([70, 255, 255]))
        yellow_ratio = (cv2.countNonZero(mask_yellow)) / (hsv.size / 3) * 100

        if yellow_ratio > self.yellow_threshold:
            return self._create_result("Yellow", yellow_ratio)

        mask_dark = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([255, 255, 70]))
        dark_ratio = (cv2.countNonZero(mask_dark)) / (hsv.size / 3) * 100

        if dark_ratio > self.dark_threshold:
            return self._create_result("Dark", dark_ratio)

        return None

    def _create_result(self, decision: str, score: float):
        return {
            "detectedBboxList": [
                {
                    "bboxName": decision,
                    "bboxScore": score,
                    "centerX": 200,
                    "centerY": 200,
                    "width": 398,
                    "height": 398
                }
            ]
        }

    def _format_filtered(self, filter_result, elapsed):
        b = filter_result["detectedBboxList"][0]
        return {
            "ai_model": self.name,
            "version": self.version,
            "classes": [b["bboxName"]],
            "decision": b["bboxName"],
            "confidence": b["bboxScore"],
            "feature_vector": None,
            "elapsed_time": round(elapsed, 4),
            "boxes": [{
                "decision": b["bboxName"],
                "confidence": b["bboxScore"],
                "box_embedding": None,
                "threshold": None,
            }],
        }

    def postprocess(self, prediction, im0_shape, img_shape, gn):
        global_embedding = self._extract_global_embedding()

        boxes = []
        lb_h, lb_w = img_shape[2], img_shape[3]  # letterboxed input H, W

        for det in prediction:  # detections per image (batch size 1 here)
            det_lb = det.clone()  # letterbox coords, used for feature extraction

            # First pass: select boxes that pass their per-class threshold.
            kept = []  # (row_index, class_name, confidence, threshold)
            for i in range(det.shape[0]):
                class_name = self.names[int(det[i, 5].item())]
                confidence = det[i, 4].item() * 100
                threshold = self.get_threshold(class_name)
                if confidence < threshold:
                    continue
                kept.append((i, class_name, confidence, threshold))

            # An image is "non-normal" if any kept box is not the normal class.
            is_non_normal = any(name != self.normal_class for _, name, _, _ in kept)

            # Per-box features only for defect images.
            box_feats = None
            feat_rows = {}
            if is_non_normal and kept:
                rows_to_embed = [
                    k for k, (_, name, _, _) in enumerate(kept)
                    if self.embed_good_boxes or name != self.normal_class
                ]
                if rows_to_embed:
                    boxes_lb = torch.stack(
                        [det_lb[kept[k][0], :4] for k in rows_to_embed], dim=0
                    ).float()
                    boxes_lb[:, [0, 2]] = boxes_lb[:, [0, 2]].clamp(0, lb_w)
                    boxes_lb[:, [1, 3]] = boxes_lb[:, [1, 3]].clamp(0, lb_h)
                    box_feats = self._extract_box_embeddings(boxes_lb)
                    feat_rows = {k: idx for idx, k in enumerate(rows_to_embed)}

            # Second pass: build the output entries.
            for k, (i, class_name, confidence, threshold) in enumerate(kept):
                embedding = None
                if box_feats is not None and k in feat_rows:
                    embedding = box_feats[feat_rows[k]].tolist()
                boxes.append({
                    "decision": class_name,
                    "confidence": confidence,
                    "box_embedding": embedding,
                    "threshold": threshold,
                })

        is_normal = not any(b["decision"] != self.normal_class for b in boxes)
        decision = self.normal_class if is_normal else "Defect"

        # Image-level confidence = the box that drove the decision.
        if is_normal:
            good_confs = [b["confidence"] for b in boxes if b["decision"] == self.normal_class]
            decision_confidence = max(good_confs) if good_confs else None
        else:
            defect_confs = [b["confidence"] for b in boxes if b["decision"] != self.normal_class]
            decision_confidence = max(defect_confs) if defect_confs else None

        return {
            "ai_model": self.name,
            "version": self.version,
            "classes": sorted({b["decision"] for b in boxes}),
            "decision": decision,
            "confidence": decision_confidence,
            "feature_vector": global_embedding,
            "elapsed_time": None,  # filled in predict()
            "boxes": boxes,
        }

    def get_threshold(self, key: str | None = None):
        if key is None:
            return dict(self._score_thresholds)
        return self._score_thresholds.get(key, self.default_threshold)

    def set_threshold(self, value: float, key: str | None = None):
        if key is None:
            raise ValueError(
                "The vaium detector uses per-class thresholds; a class_name is required. "
                f"Known classes: {sorted(self._score_thresholds)}"
            )
        self._score_thresholds[key] = value

    def get_models_info(self):
        return [{"ai_model": self.name, "model_name": "ChipDetector", "version": self.version}]

    def release(self):
        self.model = None
        self._feature_maps = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
