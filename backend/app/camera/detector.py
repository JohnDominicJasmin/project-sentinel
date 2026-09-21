from dataclasses import dataclass

import cv2
import numpy as np
import onnxruntime as ort

COCO_LABELS = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck",
    14: "bird", 15: "cat", 16: "dog",
}
OBJECT_KIND = {
    "person": "person",
    "bicycle": "vehicle", "car": "vehicle", "motorcycle": "vehicle", "bus": "vehicle", "truck": "vehicle",
    "bird": "animal", "cat": "animal", "dog": "animal",
}

Box = tuple[int, int, int, int]


@dataclass
class Detection:
    label: str
    confidence: float
    box: Box

    @property
    def kind(self) -> str:
        return OBJECT_KIND[self.label]


class YoloOnnx:

    def __init__(self, model_path: str, confidence: float = 0.45, iou: float = 0.5, threads: int = 2) -> None:
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        self.session = ort.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])
        spec = self.session.get_inputs()[0]
        self.input_name = spec.name
        self.size = int(spec.shape[2])
        self.confidence = confidence
        self.iou = iou
        self.class_ids = np.array(sorted(COCO_LABELS))

    def detect(self, frame: np.ndarray) -> list[Detection]:
        height, width = frame.shape[:2]
        scale = min(self.size / width, self.size / height)
        new_w, new_h = round(width * scale), round(height * scale)
        top, left = (self.size - new_h) // 2, (self.size - new_w) // 2
        canvas = np.full((self.size, self.size, 3), 114, np.uint8)
        canvas[top:top + new_h, left:left + new_w] = cv2.resize(frame, (new_w, new_h))
        blob = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.0

        raw = self.session.run(None, {self.input_name: blob})[0][0].T
        scores = raw[:, 4:]
        classes = scores.argmax(axis=1)
        confidences = scores[np.arange(len(classes)), classes]
        keep = (confidences >= self.confidence) & np.isin(classes, self.class_ids)
        if not keep.any():
            return []

        cx, cy, w, h = raw[keep, :4].T
        x1 = np.clip((cx - w / 2 - left) / scale, 0, width)
        y1 = np.clip((cy - h / 2 - top) / scale, 0, height)
        x2 = np.clip((cx + w / 2 - left) / scale, 0, width)
        y2 = np.clip((cy + h / 2 - top) / scale, 0, height)
        boxes = np.stack([x1, y1, x2, y2], axis=1)
        confidences, classes = confidences[keep], classes[keep]

        detections = []
        for i in non_max_suppression(boxes, confidences, self.iou):
            bx1, by1, bx2, by2 = boxes[i].round().astype(int)
            detections.append(Detection(
                label=COCO_LABELS[int(classes[i])],
                confidence=round(float(confidences[i]), 2),
                box=(int(bx1), int(by1), int(bx2 - bx1), int(by2 - by1)),
            ))
        return detections


def non_max_suppression(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> list[int]:
    order = scores.argsort()[::-1]
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    kept = []
    while order.size:
        best, rest = order[0], order[1:]
        kept.append(int(best))
        xx1 = np.maximum(boxes[best, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[best, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[best, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[best, 3], boxes[rest, 3])
        overlap = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = overlap / (areas[best] + areas[rest] - overlap + 1e-9)
        order = rest[iou < threshold]
    return kept
