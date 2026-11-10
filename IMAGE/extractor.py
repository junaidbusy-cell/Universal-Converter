
import re
from typing import Any, Dict, List, Optional, Tuple
from .models import BoundingBox, OCRRegion, OCRTable, OCRFormula, OCRPage

def detect_columns(regions: List[OCRRegion], page_width: int) -> Tuple[bool, float]:

    if len(regions) < 4 or page_width <= 0:
        return False, page_width / 2.0

    midpoint = page_width / 2.0
    left_boxes = 0
    right_boxes = 0
    spanning_boxes = 0

    for r in regions:

        if r.bbox.x1 < midpoint * 0.85 and r.bbox.x2 > midpoint * 1.15:
            spanning_boxes += 1
        elif r.bbox.x2 <= midpoint * 1.05:
            left_boxes += 1
        elif r.bbox.x1 >= midpoint * 0.95:
            right_boxes += 1

    total_column_boxes = left_boxes + right_boxes

    if total_column_boxes >= 4 and left_boxes >= 2 and right_boxes >= 2:
        if spanning_boxes / float(len(regions)) < 0.40:
            return True, midpoint

    return False, midpoint

def reconstruct_reading_order(
    regions: List[OCRRegion],
    page_width: int,
) -> List[OCRRegion]:

    if not regions:
        return []

    is_two_col, split_x = detect_columns(regions, page_width)

    if not is_two_col:

        sorted_regions = sorted(regions, key=lambda r: (round(r.bbox.y1 / 15.0), r.bbox.x1))
    else:

        top_spanning: List[OCRRegion] = []
        left_column: List[OCRRegion] = []
        right_column: List[OCRRegion] = []
        bottom_spanning: List[OCRRegion] = []

        col_boxes = [r for r in regions if not (r.bbox.x1 < split_x * 0.85 and r.bbox.x2 > split_x * 1.15)]
        min_col_y = min((r.bbox.y1 for r in col_boxes), default=0)
        max_col_y = max((r.bbox.y2 for r in col_boxes), default=1e6)

        for r in regions:
            is_spanning = r.bbox.x1 < split_x * 0.85 and r.bbox.x2 > split_x * 1.15
            if is_spanning:
                if r.bbox.y2 <= min_col_y + 30:
                    top_spanning.append(r)
                elif r.bbox.y1 >= max_col_y - 30:
                    bottom_spanning.append(r)
                else:

                    left_column.append(r)
            elif r.bbox.x2 <= split_x * 1.05:
                left_column.append(r)
            else:
                right_column.append(r)

        top_sorted = sorted(top_spanning, key=lambda r: (r.bbox.y1, r.bbox.x1))
        left_sorted = sorted(left_column, key=lambda r: (r.bbox.y1, r.bbox.x1))
        right_sorted = sorted(right_column, key=lambda r: (r.bbox.y1, r.bbox.x1))
        bottom_sorted = sorted(bottom_spanning, key=lambda r: (r.bbox.y1, r.bbox.x1))

        sorted_regions = top_sorted + left_sorted + right_sorted + bottom_sorted

    ordered_regions: List[OCRRegion] = []
    for idx, reg in enumerate(sorted_regions):
        reg.reading_order = idx + 1
        ordered_regions.append(reg)

    return ordered_regions

def classify_region_type(region: OCRRegion, avg_height: float) -> str:

    text = region.text.strip()
    if not text:
        return "paragraph"

    if any(sym in text for sym in ("$$", "\\int", "\\sum", "\\frac", "√", "±", "²", "³")) or (
        text.startswith("$") and text.endswith("$")
    ):
        return "formula"

    is_large = region.bbox.height > (avg_height * 1.25)
    is_short = len(text) < 80
    is_title_cased = text.isupper() or text.istitle()

    heading_patterns = (
        r"^(chapter|section|part|appendix)\s+\d+",
        r"^\d+(\.\d+)*\s+[A-Z]",
        r"^(introduction|abstract|summary|conclusion|references|table of contents)$",
    )

    if any(re.match(pat, text, re.I) for pat in heading_patterns):
        return "heading"

    if is_large and is_short and is_title_cased and not text.endswith("."):
        return "heading"

    if re.match(r"^(\d+[\.\)]|[-•*])\s+", text):
        return "list"

    return "paragraph"

def reconstruct_paragraphs(regions: List[OCRRegion]) -> List[OCRRegion]:

    if not regions:
        return []

    heights = [r.bbox.height for r in regions if r.bbox.height > 0]
    avg_height = sum(heights) / float(len(heights)) if heights else 20.0

    for r in regions:
        if r.type == "paragraph":
            r.type = classify_region_type(r, avg_height)
            if r.type == "heading":
                r.extra["level"] = 2 if r.bbox.height > avg_height * 1.5 else 3

    merged: List[OCRRegion] = []
    curr = regions[0]

    for next_r in regions[1:]:

        can_merge = False

        if curr.type == "paragraph" and next_r.type == "paragraph":

            line_gap = next_r.bbox.y1 - curr.bbox.y2

            if -5 <= line_gap <= (avg_height * 1.8):

                h_overlap = (
                    min(curr.bbox.x2, next_r.bbox.x2) - max(curr.bbox.x1, next_r.bbox.x1)
                ) > 0 or abs(curr.bbox.x1 - next_r.bbox.x1) < (avg_height * 2.0)

                if h_overlap:

                    prev_text = curr.text.strip()
                    if not (prev_text.endswith((".", "!", "?")) and next_r.text[:1].isupper() and line_gap > avg_height * 0.9):
                        can_merge = True

        if can_merge:

            prev_t = curr.text.strip()
            next_t = next_r.text.strip()
            if (
                prev_t.endswith("-")
                and not prev_t.endswith(("--", " -"))
                and len(prev_t) > 1
                and prev_t[-2].isalpha()
                and next_t[:1].isalpha()
            ):
                combined_text = f"{prev_t[:-1].rstrip()}{next_t}"
            else:
                combined_text = f"{prev_t} {next_t}"

            new_bbox = BoundingBox(
                x1=min(curr.bbox.x1, next_r.bbox.x1),
                y1=min(curr.bbox.y1, next_r.bbox.y1),
                x2=max(curr.bbox.x2, next_r.bbox.x2),
                y2=max(curr.bbox.y2, next_r.bbox.y2),
            )

            len_c = max(1, len(curr.text))
            len_n = max(1, len(next_r.text))
            avg_conf = (curr.confidence * len_c + next_r.confidence * len_n) / float(len_c + len_n)

            curr = OCRRegion(
                region_id=curr.region_id,
                type="paragraph",
                text=combined_text,
                bbox=new_bbox,
                polygon=[],
                confidence=avg_conf,
                reading_order=curr.reading_order,
                extra=curr.extra,
            )
        else:
            merged.append(curr)
            curr = next_r

    merged.append(curr)
    return merged

def extract_ocr_page(
    page_number: int,
    raw_regions: List[OCRRegion],
    page_width: int,
    page_height: int,
    orientation: int = 0,
    transforms: Optional[Dict[str, Any]] = None,
    tables: Optional[List[OCRTable]] = None,
    formulas: Optional[List[OCRFormula]] = None,
    min_confidence: float = 0.0,
) -> OCRPage:

    if min_confidence > 0.0:
        raw_regions = [r for r in raw_regions if r.confidence >= min_confidence]

    ordered_regions = reconstruct_reading_order(raw_regions, page_width=page_width)

    processed_regions = reconstruct_paragraphs(ordered_regions)

    for idx, reg in enumerate(processed_regions):
        reg.reading_order = idx + 1

    return OCRPage(
        page_number=page_number,
        width=page_width,
        height=page_height,
        orientation=orientation,
        transforms=transforms or {},
        regions=processed_regions,
        tables=tables or [],
        formulas=formulas or [],
        images=[],
        warnings=[],
    )
