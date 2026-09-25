import json
import base64
import torch
import sys
import os


# Add OmniParser to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "OmniParser"))
import config  # patches sys.path before importing util.utils
from util.utils import get_som_labeled_img, check_ocr_box, get_caption_model_processor, get_yolo_model  # type: ignore[import]


class OmniParserClient:
    _instance = None

    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[OmniParser] Loading models on {self.device}...")
        self.yolo_model = get_yolo_model(model_path=config.YOLO_MODEL_PATH)
        self.caption_model_processor = get_caption_model_processor(
            model_name="florence2",
            model_name_or_path=config.CAPTION_MODEL_PATH,
            device=self.device,
        )
        print("[OmniParser] Models loaded.")
        self._step_counter = 0

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def parse(self, image_path: str):
        ocr_bbox_rslt, _ = check_ocr_box(
            image_path, display_img=False, output_bb_format="xyxy"
        )
        text, ocr_bbox = ocr_bbox_rslt

        labeled_img, coordinates, parsed_content = get_som_labeled_img(
            image_path,
            self.yolo_model,
            BOX_TRESHOLD=config.BOX_THRESHOLD,
            ocr_bbox=ocr_bbox,
            ocr_text=text,
            caption_model_processor=self.caption_model_processor,
        )
        return labeled_img, coordinates, parsed_content

    def parse_and_save(self, image_path: str, step_name: str):
        """
        Parses the image and saves a step-numbered labeled screenshot + JSON
        for debugging, e.g. '01_after_login_click_labeled.png'.
        """
        labeled_img_b64, coordinates, parsed_content = self.parse(image_path)

        self._step_counter += 1
        prefix = f"{self._step_counter:02d}_{step_name}"

        labeled_path = os.path.join(config.SCREENSHOT_DIR, f"{prefix}_labeled.png")
        json_path = os.path.join(config.SCREENSHOT_DIR, f"{prefix}_parsed.json")

        with open(labeled_path, "wb") as f:
            f.write(base64.b64decode(labeled_img_b64))
        with open(json_path, "w") as f:
            json.dump(parsed_content, f, indent=2)

        print(f"[debug] Saved {labeled_path} and {json_path}")
        return parsed_content

    def save_outputs(self, labeled_img_b64, parsed_content):
        with open(config.LABELED_SCREENSHOT_PATH, "wb") as f:
            f.write(base64.b64decode(labeled_img_b64))
        with open(config.PARSED_JSON_PATH, "w") as f:
            json.dump(parsed_content, f, indent=2)