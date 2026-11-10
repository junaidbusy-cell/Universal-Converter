
import warnings
warnings.filterwarnings("ignore", message=".*ccache.*", category=UserWarning)

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image

from .models import BoundingBox, OCRRegion, OCRTable, OCRFormula

class OCRError(Exception):

    pass

class OCREngineNotInstalledError(OCRError):

    pass

def resolve_device(requested_device: str = "auto") -> str:

    req = requested_device.lower().strip()
    if req in ("cpu", "none"):
        return "cpu"

    try:
        import paddle
        if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            return "gpu:0" if req == "auto" else req
    except Exception:
        pass

    return "cpu"

def is_devanagari(text: str) -> bool:

    return any("\u0900" <= ch <= "\u097f" for ch in text)

class BaseOCREngine(ABC):

    @abstractmethod
    def detect_and_recognize(
        self,
        image: Image.Image,
        lang: str = "en",
        tier: str = "medium",
        mode: str = "auto",
    ) -> List[OCRRegion]:

        pass

    @abstractmethod
    def get_engine_info(self) -> Dict[str, Any]:

        pass

class MockOCREngine(BaseOCREngine):

    def __init__(self, predefined_regions: Optional[List[OCRRegion]] = None):
        self.predefined_regions = predefined_regions or []

    def detect_and_recognize(
        self,
        image: Image.Image,
        lang: str = "en",
        tier: str = "medium",
        mode: str = "auto",
    ) -> List[OCRRegion]:
        if self.predefined_regions:
            return list(self.predefined_regions)

        w, h = image.size
        regions = [
            OCRRegion(
                region_id="reg_001",
                type="heading",
                text="Document Title",
                bbox=BoundingBox(x1=w * 0.1, y1=h * 0.05, x2=w * 0.9, y2=h * 0.15),
                polygon=[
                    [w * 0.1, h * 0.05],
                    [w * 0.9, h * 0.05],
                    [w * 0.9, h * 0.15],
                    [w * 0.1, h * 0.15],
                ],
                confidence=0.99,
                reading_order=1,
                extra={"level": 1},
            ),
            OCRRegion(
                region_id="reg_002",
                type="paragraph",
                text="This is an extracted paragraph recognized by the OCR engine.",
                bbox=BoundingBox(x1=w * 0.1, y1=h * 0.20, x2=w * 0.9, y2=h * 0.35),
                polygon=[
                    [w * 0.1, h * 0.20],
                    [w * 0.9, h * 0.20],
                    [w * 0.9, h * 0.35],
                    [w * 0.1, h * 0.35],
                ],
                confidence=0.96,
                reading_order=2,
            ),
        ]
        return regions

    def get_engine_info(self) -> Dict[str, Any]:
        return {
            "engine": "MockOCR",
            "version": "1.0.0",
            "device": "cpu",
            "tier": "mock",
        }

_PADDLE_OCR_CACHE: Dict[Tuple[str, str, str], Any] = {}

class PaddleOCREngine(BaseOCREngine):

    def __init__(
        self,
        lang: str = "en",
        tier: str = "medium",
        device: str = "auto",
    ):
        self.lang = lang
        self.tier = tier
        self.device = resolve_device(device)
        self._ocr_instance: Optional[Any] = None
        self._initialized = False

    def _ensure_initialized(self):
        if self._initialized:
            return

        cache_key = (self.lang, self.tier.lower(), self.device)
        if cache_key in _PADDLE_OCR_CACHE:
            self._ocr_instance = _PADDLE_OCR_CACHE[cache_key]
            self._initialized = True
            return

        try:
            import paddle
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise OCREngineNotInstalledError(
                f"PaddleOCR is not installed in the environment: {e}. "
                f"Install with: pip install -r requirements-ocr.txt"
            )

        use_gpu = self.device.startswith("gpu")
        if use_gpu:
            try:
                paddle.set_device(self.device)
            except Exception:
                use_gpu = False
                paddle.set_device("cpu")
                self.device = "cpu"
        else:
            paddle.set_device("cpu")

        tier_str = self.tier.lower()
        if tier_str == "tiny":
            det_limit = 720
        elif tier_str == "small":
            det_limit = 960
        elif tier_str in ("medium", "mid"):
            det_limit = 1200
        else:
            det_limit = 1600

        try:
            ocr_kwargs_v3 = {
                "lang": self.lang,
                "device": self.device,
                "enable_mkldnn": False,
                "use_textline_orientation": True,
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "text_det_limit_side_len": det_limit,
            }
            self._ocr_instance = PaddleOCR(**ocr_kwargs_v3)
            _PADDLE_OCR_CACHE[cache_key] = self._ocr_instance
            self._initialized = True
        except TypeError:

            try:
                ocr_kwargs_v2 = {
                    "lang": self.lang,
                    "use_angle_cls": True,
                    "use_gpu": use_gpu,
                    "show_log": False,
                    "det_limit_side_len": det_limit,
                }
                self._ocr_instance = PaddleOCR(**ocr_kwargs_v2)
                _PADDLE_OCR_CACHE[cache_key] = self._ocr_instance
                self._initialized = True
            except Exception as err:
                raise OCRError(f"Failed to initialize PaddleOCR engine: {err}")
        except Exception as err:
            raise OCRError(f"Failed to initialize PaddleOCR engine: {err}")

    def detect_and_recognize(
        self,
        image: Image.Image,
        lang: str = "en",
        tier: str = "medium",
        mode: str = "auto",
    ) -> List[OCRRegion]:
        self._ensure_initialized()

        try:
            import numpy as np
        except ImportError:
            raise OCRError("NumPy is required for PaddleOCR inference.")

        rgb_img = image.convert("RGB")
        img_array = np.array(rgb_img)

        regions: List[OCRRegion] = []

        if hasattr(self._ocr_instance, "predict"):
            try:
                preds = list(self._ocr_instance.predict(img_array))
                if preds and (isinstance(preds[0], dict) or hasattr(preds[0], "get")):
                    p = preds[0]
                    rec_texts = p.get("rec_texts", [])
                    rec_scores = p.get("rec_scores", [])
                    rec_polys = p.get("rec_polys", p.get("dt_polys", []))
                    rec_boxes = p.get("rec_boxes", [])

                    for idx, (rec_text, score) in enumerate(zip(rec_texts, rec_scores)):
                        text_str = str(rec_text).strip()
                        if not text_str:
                            continue

                        score_val = float(score) if score is not None else 1.0

                        if idx < len(rec_polys):
                            poly = rec_polys[idx]
                            poly_pts = poly.tolist() if hasattr(poly, "tolist") else [list(pt) for pt in poly]
                            bbox = BoundingBox.from_polygon(poly_pts)
                        elif idx < len(rec_boxes):
                            b = rec_boxes[idx]
                            bbox = BoundingBox(x1=float(b[0]), y1=float(b[1]), x2=float(b[2]), y2=float(b[3]))
                            poly_pts = [[bbox.x1, bbox.y1], [bbox.x2, bbox.y1], [bbox.x2, bbox.y2], [bbox.x1, bbox.y2]]
                        else:
                            bbox = BoundingBox(x1=0.0, y1=0.0, x2=float(image.width), y2=float(image.height))
                            poly_pts = [[0.0, 0.0], [float(image.width), 0.0], [float(image.width), float(image.height)], [0.0, float(image.height)]]

                        regions.append(
                            OCRRegion(
                                region_id=f"reg_{idx + 1:04d}",
                                type="paragraph",
                                text=text_str,
                                bbox=bbox,
                                polygon=poly_pts,
                                confidence=score_val,
                                reading_order=idx + 1,
                                line_number=idx + 1,
                            )
                        )
                    return regions
            except Exception:

                pass

        try:
            try:
                raw_results = self._ocr_instance.ocr(img_array)
            except Exception:
                raw_results = self._ocr_instance.ocr(img_array, cls=True)
        except Exception as e:
            raise OCRError(f"PaddleOCR inference failed on image: {e}")

        if not raw_results or not raw_results[0]:
            return regions

        line_results = raw_results[0]
        if isinstance(line_results, dict):
            p = line_results
            rec_texts = p.get("rec_texts", [])
            rec_scores = p.get("rec_scores", [])
            rec_polys = p.get("rec_polys", p.get("dt_polys", []))
            for idx, (rec_text, score) in enumerate(zip(rec_texts, rec_scores)):
                text_str = str(rec_text).strip()
                if not text_str:
                    continue
                score_val = float(score) if score is not None else 1.0
                if idx < len(rec_polys):
                    poly = rec_polys[idx]
                    poly_pts = poly.tolist() if hasattr(poly, "tolist") else [list(pt) for pt in poly]
                    bbox = BoundingBox.from_polygon(poly_pts)
                else:
                    bbox = BoundingBox(x1=0.0, y1=0.0, x2=float(image.width), y2=float(image.height))
                    poly_pts = [[0.0, 0.0], [float(image.width), 0.0], [float(image.width), float(image.height)], [0.0, float(image.height)]]
                regions.append(
                    OCRRegion(
                        region_id=f"reg_{idx + 1:04d}",
                        type="paragraph",
                        text=text_str,
                        bbox=bbox,
                        polygon=poly_pts,
                        confidence=score_val,
                        reading_order=idx + 1,
                        line_number=idx + 1,
                    )
                )
            return regions

        for idx, item in enumerate(line_results):

            poly_pts = item[0]
            text_info = item[1]
            rec_text = str(text_info[0]).strip()
            score = float(text_info[1])

            if not rec_text:
                continue

            bbox = BoundingBox.from_polygon(poly_pts)
            regions.append(
                OCRRegion(
                    region_id=f"reg_{idx + 1:04d}",
                    type="paragraph",
                    text=rec_text,
                    bbox=bbox,
                    polygon=poly_pts,
                    confidence=score,
                    reading_order=idx + 1,
                    line_number=idx + 1,
                )
            )

        return regions

    def get_engine_info(self) -> Dict[str, Any]:
        return {
            "engine": "PaddleOCR",
            "version": "3.7.0",
            "model": "PP-OCRv6",
            "tier": self.tier,
            "device": self.device,
            "language": self.lang,
        }

class TesseractOCREngine(BaseOCREngine):

    def __init__(self, lang: str = "eng"):
        self.lang = lang

    def detect_and_recognize(
        self,
        image: Image.Image,
        lang: str = "en",
        tier: str = "medium",
        mode: str = "auto",
    ) -> List[OCRRegion]:
        try:
            import pytesseract
            from pytesseract import Output
        except ImportError as e:
            raise OCREngineNotInstalledError(
                f"pytesseract is not installed: {e}. "
                f"Install with: pip install pytesseract and ensure tesseract-ocr system binary is installed."
            )

        tess_lang = "hin" if lang == "hi" else (self.lang or "eng")

        if os.name == "nt":
            for win_tess in [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]:
                if os.path.exists(win_tess):
                    pytesseract.pytesseract.tesseract_cmd = win_tess
                    break

        try:
            data = pytesseract.image_to_data(image, lang=tess_lang, output_type=Output.DICT)
        except Exception as err:
            raise OCRError(f"Tesseract OCR inference failed: {err}")

        regions: List[OCRRegion] = []
        n_boxes = len(data.get("text", []))
        line_idx = 1

        for i in range(n_boxes):
            text = data["text"][i].strip()
            conf = float(data["conf"][i])
            if not text or conf < 0:
                continue

            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            bbox = BoundingBox(x1=float(x), y1=float(y), x2=float(x + w), y2=float(y + h))
            regions.append(
                OCRRegion(
                    region_id=f"reg_{line_idx:04d}",
                    type="paragraph",
                    text=text,
                    bbox=bbox,
                    polygon=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                    confidence=round(conf / 100.0, 4),
                    reading_order=line_idx,
                )
            )
            line_idx += 1

        return regions

    def get_engine_info(self) -> Dict[str, Any]:
        return {
            "engine": "Tesseract",
            "version": "5.x",
            "device": "cpu",
            "language": self.lang,
        }

def get_ocr_engine(
    engine_name: str = "auto",
    device: str = "auto",
    tier: str = "high",
    lang: str = "en",
    mock_regions: Optional[List[OCRRegion]] = None,
) -> BaseOCREngine:

    name = engine_name.lower().strip()

    if name in ("mock", "test"):
        return MockOCREngine(predefined_regions=mock_regions)

    if name == "auto":

        try:
            import paddleocr
            return PaddleOCREngine(lang=lang, tier=tier, device=device)
        except ImportError:

            return MockOCREngine(predefined_regions=mock_regions)

    if name == "paddle":
        return PaddleOCREngine(lang=lang, tier=tier, device=device)

    if name == "tesseract":
        return TesseractOCREngine(lang="hin" if lang == "hi" else "eng")

    raise ValueError(f"Unknown OCR engine '{engine_name}'. Supported: 'paddle', 'mock', 'tesseract', 'auto'")
