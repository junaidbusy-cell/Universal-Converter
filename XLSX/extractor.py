
import re
from datetime import datetime, date, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.styles.numbers import is_date_format
from openpyxl.utils.datetime import from_excel, CALENDAR_WINDOWS_1900, CALENDAR_MAC_1904

from common.models import Metadata
from .models import CellModel, TableRange, WorksheetModel, WorkbookModel
from .parser import get_true_sheet_dimensions, extract_workbook_metadata
from .assets import XLSXAssetManager

def _is_empty_value(val: Any) -> bool:

    if val is None:
        return True
    if isinstance(val, str) and not val.strip():
        return True
    return False

def _extract_chart_title(chart: Any) -> str:

    title_obj = getattr(chart, "title", None)
    if not title_obj:
        return chart.__class__.__name__

    if isinstance(title_obj, str):
        return title_obj.strip()

    try:
        tx = getattr(title_obj, "tx", None)
        if tx:
            rich = getattr(tx, "rich", None)
            if rich and hasattr(rich, "paragraphs"):
                parts: List[str] = []
                for p in rich.paragraphs:
                    for r in getattr(p, "r", []):
                        if getattr(r, "t", None):
                            parts.append(str(r.t))
                if parts:
                    return "".join(parts).strip()

            str_ref = getattr(tx, "strRef", None)
            if str_ref and hasattr(str_ref, "f"):
                return f"Chart [{str_ref.f}]"
    except Exception:
        pass

    return chart.__class__.__name__

def _build_merged_map(ws: Worksheet) -> Dict[str, str]:

    merged_map: Dict[str, str] = {}
    if not hasattr(ws, "merged_cells") or not ws.merged_cells:
        return merged_map
    for rng in ws.merged_cells.ranges:
        origin_coord = f"{get_column_letter(rng.min_col)}{rng.min_row}"
        for row in range(rng.min_row, rng.max_row + 1):
            for col in range(rng.min_col, rng.max_col + 1):
                coord = f"{get_column_letter(col)}{row}"
                merged_map[coord] = origin_coord
    return merged_map

def _resolve_cell_value_and_type(
    cell_f: Any,
    cell_v: Any,
    epoch: Any = CALENDAR_WINDOWS_1900,
) -> Tuple[Any, Optional[str], str, Optional[str], Any]:

    raw_formula = getattr(cell_f, "value", None)
    cached_val = getattr(cell_v, "value", None)

    is_formula = False
    formula_str = None
    if isinstance(raw_formula, str) and raw_formula.startswith("="):
        is_formula = True
        formula_str = raw_formula
    elif getattr(cell_f, "data_type", None) == "f":
        is_formula = True
        formula_str = f"={raw_formula}" if not str(raw_formula).startswith("=") else str(raw_formula)

    val = cached_val if (cached_val is not None) else raw_formula

    if getattr(cell_f, "data_type", None) == "e" or getattr(cell_v, "data_type", None) == "e":
        return val, str(val) if val is not None else "#ERROR!", "e", formula_str, cached_val
    if isinstance(val, str) and val.startswith("#") and val.endswith("!"):
        return val, val, "e", formula_str, cached_val

    is_date = False
    if isinstance(val, (datetime, date, time)):
        is_date = True
    else:
        num_fmt = getattr(cell_f, "number_format", None) or ""
        if (getattr(cell_f, "is_date", False) or is_date_format(num_fmt)) and isinstance(val, (int, float)):
            try:

                if val >= 0:
                    val = from_excel(val, offset=epoch)
                    is_date = True
            except Exception:
                pass

    if is_date:
        if isinstance(val, datetime):
            formatted_val = val.isoformat()
        elif isinstance(val, date):
            formatted_val = val.isoformat()
        elif isinstance(val, time):
            formatted_val = val.strftime("%H:%M:%S")
        else:
            formatted_val = str(val)
        return formatted_val, formatted_val, "d", formula_str, cached_val

    if _is_empty_value(val):
        return None, None, "empty", formula_str, cached_val

    if isinstance(val, bool):
        return val, str(val), "b", formula_str, cached_val

    if isinstance(val, (int, float)):
        return val, str(val), "n", formula_str, cached_val

    str_val = str(val)
    # Sanitize string: clean openpyxl XML escaped control chars and binary header remnants
    if "_x00" in str_val or "\ufffd" in str_val or "\u0871" in str_val:
        str_val = re.sub(r"_x[0-9a-fA-F]{4}_", "", str_val)
        str_val = re.sub(r"^[^\x20-\x7e]+", "", str_val).strip()

    return str_val, str_val, ("f" if is_formula else "s"), formula_str, cached_val

def extract_cell(
    cell_f: Any,
    cell_v: Any,
    merged_map: Dict[str, str],
    epoch: Any = CALENDAR_WINDOWS_1900,
) -> CellModel:

    coord = getattr(cell_f, "coordinate", "")
    row = getattr(cell_f, "row", 1)
    col = getattr(cell_f, "column", 1)

    is_merged = coord in merged_map
    merge_origin = merged_map.get(coord)

    val, raw_val, data_type, formula_str, cached_val = _resolve_cell_value_and_type(
        cell_f, cell_v, epoch=epoch
    )

    hyperlink = None
    if getattr(cell_f, "hyperlink", None):
        hlink = cell_f.hyperlink
        hyperlink = getattr(hlink, "target", None) or str(hlink)

    comment = None
    if getattr(cell_f, "comment", None):
        cmt = cell_f.comment
        comment = getattr(cmt, "text", None) or getattr(cmt, "content", None)
        if comment:
            comment = str(comment).strip()

    num_format = getattr(cell_f, "number_format", None)
    if num_format == "General":
        num_format = None

    return CellModel(
        coordinate=coord,
        row=row,
        col=col,
        value=val,
        raw_value=raw_val,
        formula=formula_str,
        cached_value=cached_val,
        data_type=data_type,
        number_format=num_format,
        hyperlink=hyperlink,
        comment=comment,
        is_merged=is_merged,
        merge_origin=merge_origin,
    )

def _detect_sheet_tables(
    ws_formula: Worksheet,
    cells_dict: Dict[str, CellModel],
    min_row: int,
    max_row: int,
    min_col: int,
    max_col: int,
) -> List[TableRange]:

    tables: List[TableRange] = []

    formal_tables = getattr(ws_formula, "tables", None)
    if formal_tables:
        for tbl in formal_tables.values():
            ref = getattr(tbl, "ref", None)
            if not ref:
                continue
            try:
                t_min_col, t_min_row, t_max_col, t_max_row = range_boundaries(ref)
                headers: List[str] = []

                for c in range(t_min_col, t_max_col + 1):
                    coord = f"{get_column_letter(c)}{t_min_row}"
                    cell = cells_dict.get(coord)
                    headers.append(str(cell.value) if (cell and cell.value is not None) else f"Col_{c}")

                data_rows: List[List[Any]] = []
                for r in range(t_min_row + 1, t_max_row + 1):
                    row_vals: List[Any] = []
                    for c in range(t_min_col, t_max_col + 1):
                        coord = f"{get_column_letter(c)}{r}"
                        cell = cells_dict.get(coord)
                        row_vals.append(cell.value if (cell and cell.value is not None) else "")
                    data_rows.append(row_vals)

                name = getattr(tbl, "displayName", None) or getattr(tbl, "name", None) or f"Table_{len(tables) + 1}"
                tables.append(TableRange(
                    name=name,
                    range_str=ref,
                    start_row=t_min_row,
                    end_row=t_max_row,
                    start_col=t_min_col,
                    end_col=t_max_col,
                    headers=headers,
                    rows=data_rows,
                    is_formal=True,
                ))
            except Exception:
                continue

    formal_row_ranges = [(t.start_row, t.end_row) for t in tables]

    row_has_data: Dict[int, bool] = {}
    for r in range(min_row, max_row + 1):
        has_val = False
        for c in range(min_col, max_col + 1):
            coord = f"{get_column_letter(c)}{r}"
            cell = cells_dict.get(coord)
            if cell and not _is_empty_value(cell.value):
                has_val = True
                break
        row_has_data[r] = has_val

    clusters: List[Tuple[int, int]] = []
    current_start: Optional[int] = None
    consecutive_empty = 0

    for r in range(min_row, max_row + 1):
        if row_has_data[r]:
            if current_start is None:
                current_start = r
            consecutive_empty = 0
        else:
            consecutive_empty += 1
            if consecutive_empty >= 2 and current_start is not None:

                clusters.append((current_start, r - consecutive_empty))
                current_start = None

    if current_start is not None:
        clusters.append((current_start, max_row))

    if not clusters and not tables:
        return []

    for idx, (c_start_row, c_end_row) in enumerate(clusters, start=1):

        if any(f_start <= c_start_row and c_end_row <= f_end for f_start, f_end in formal_row_ranges):
            continue

        c_min_col, c_max_col = None, None
        for r in range(c_start_row, c_end_row + 1):
            for c in range(min_col, max_col + 1):
                coord = f"{get_column_letter(c)}{r}"
                cell = cells_dict.get(coord)
                if cell and not _is_empty_value(cell.value):
                    if c_min_col is None or c < c_min_col:
                        c_min_col = c
                    if c_max_col is None or c > c_max_col:
                        c_max_col = c

        if c_min_col is None:
            continue

        headers: List[str] = []
        for c in range(c_min_col, c_max_col + 1):
            coord = f"{get_column_letter(c)}{c_start_row}"
            cell = cells_dict.get(coord)
            headers.append(str(cell.value) if (cell and cell.value is not None) else f"Column_{c}")

        data_rows: List[List[Any]] = []
        for r in range(c_start_row + 1, c_end_row + 1):
            row_vals: List[Any] = []
            for c in range(c_min_col, c_max_col + 1):
                coord = f"{get_column_letter(c)}{r}"
                cell = cells_dict.get(coord)
                row_vals.append(cell.value if (cell and cell.value is not None) else "")
            data_rows.append(row_vals)

        range_str = f"{get_column_letter(c_min_col)}{c_start_row}:{get_column_letter(c_max_col)}{c_end_row}"
        total_tbls = len(tables) + 1
        table_name = ws_formula.title if (not tables and len(clusters) == 1) else f"Table_{total_tbls}"

        tables.append(TableRange(
            name=table_name,
            range_str=range_str,
            start_row=c_start_row,
            end_row=c_end_row,
            start_col=c_min_col,
            end_col=c_max_col,
            headers=headers,
            rows=data_rows,
            is_formal=False,
        ))

    return tables

def extract_worksheet(
    ws_formula: Worksheet,
    ws_value: Worksheet,
    sheet_index: int,
    epoch: Any = CALENDAR_WINDOWS_1900,
    asset_mgr: Optional[XLSXAssetManager] = None,
) -> WorksheetModel:

    sheet_name = ws_formula.title
    sheet_state = getattr(ws_formula, "sheet_state", "visible") or "visible"
    is_visible = (sheet_state == "visible")

    min_row, max_row, min_col, max_col = get_true_sheet_dimensions(ws_formula)

    v_min_row, v_max_row, v_min_col, v_max_col = get_true_sheet_dimensions(ws_value)
    if v_min_row < min_row or v_max_row > max_row:
        min_row = min(min_row, v_min_row)
        max_row = max(max_row, v_max_row)
        min_col = min(min_col, v_min_col)
        max_col = max(max_col, v_max_col)

    is_empty = (max_row < min_row) or (max_row == 1 and min_row == 1 and _is_empty_value(ws_formula.cell(1, 1).value) and _is_empty_value(ws_value.cell(1, 1).value))

    merged_map = _build_merged_map(ws_formula)
    merged_ranges_list = [str(r) for r in ws_formula.merged_cells.ranges] if hasattr(ws_formula, "merged_cells") and ws_formula.merged_cells else []

    cells_dict: Dict[str, CellModel] = {}
    comments_list: List[Dict[str, Any]] = []

    if not is_empty:

        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                cell_f = ws_formula.cell(row=r, column=c)
                cell_v = ws_value.cell(row=r, column=c)
                cell_model = extract_cell(cell_f, cell_v, merged_map, epoch=epoch)
                cells_dict[cell_model.coordinate] = cell_model

                if cell_model.comment:
                    comments_list.append({
                        "coordinate": cell_model.coordinate,
                        "text": cell_model.comment,
                    })

        for coord, cell_model in cells_dict.items():
            if cell_model.is_merged and cell_model.merge_origin and cell_model.merge_origin != coord:
                origin_cell = cells_dict.get(cell_model.merge_origin)
                if origin_cell and origin_cell.value is not None:
                    cell_model.value = origin_cell.value
                    cell_model.raw_value = origin_cell.raw_value
                    cell_model.cached_value = origin_cell.cached_value
                    cell_model.data_type = origin_cell.data_type

    total_rows = (max_row - min_row + 1) if not is_empty else 0
    total_cols = (max_col - min_col + 1) if not is_empty else 0

    tables = _detect_sheet_tables(ws_formula, cells_dict, min_row, max_row, min_col, max_col) if not is_empty else []

    charts_list: List[Dict[str, Any]] = []
    for chart in getattr(ws_formula, "_charts", []):
        chart_title = _extract_chart_title(chart)
        chart_type = chart.__class__.__name__
        chart_anchor = getattr(chart, "anchor", None)
        charts_list.append({
            "title": chart_title,
            "type": chart_type,
            "anchor": str(chart_anchor) if chart_anchor else None,
        })

    images_list: List[Dict[str, Any]] = []
    for img_obj in getattr(ws_formula, "_images", []):
        if asset_mgr:
            img_dict = asset_mgr.extract_image(img_obj, sheet_name=sheet_name)
            if img_dict:
                images_list.append(img_dict)

    return WorksheetModel(
        name=sheet_name,
        index=sheet_index,
        state=sheet_state,
        is_visible=is_visible,
        min_row=min_row if not is_empty else 1,
        max_row=max_row if not is_empty else 1,
        min_col=min_col if not is_empty else 1,
        max_col=max_col if not is_empty else 1,
        total_rows=total_rows,
        total_cols=total_cols,
        tables=tables,
        cells=cells_dict,
        merged_ranges=merged_ranges_list,
        charts=charts_list,
        images=images_list,
        comments=comments_list,
    )

def extract_workbook(
    wb_formula: openpyxl.Workbook,
    wb_value: openpyxl.Workbook,
    source_path: Union[str, Path],
    asset_mgr: Optional[XLSXAssetManager] = None,
) -> WorkbookModel:

    src_str = str(source_path)
    stem = Path(source_path).stem

    meta = extract_workbook_metadata(wb_formula)
    title = meta.title or stem.replace("_", " ").title()

    epoch = CALENDAR_WINDOWS_1900
    if getattr(wb_formula, "epoch", None) == CALENDAR_MAC_1904:
        epoch = CALENDAR_MAC_1904

    sheets: List[WorksheetModel] = []
    for idx, sheet_name in enumerate(wb_formula.sheetnames):
        ws_f = wb_formula[sheet_name]
        ws_v = wb_value[sheet_name]
        sheet_model = extract_worksheet(
            ws_formula=ws_f,
            ws_value=ws_v,
            sheet_index=idx,
            epoch=epoch,
            asset_mgr=asset_mgr,
        )
        sheets.append(sheet_model)

    defined_names = meta.extra.get("defined_names", [])

    wb_model = WorkbookModel(
        source=src_str,
        title=title,
        metadata=meta,
        sheets=sheets,
        defined_names=defined_names,
    )
    wb_model.update_stats()
    return wb_model
