
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
from lxml import etree

from common.models import Metadata

SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm", ".xls", ".xlsb", ".ods"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100.0

OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

class XLSXError(Exception):

    pass

class UnsupportedXLSXError(XLSXError):

    pass

class CorruptWorkbookError(XLSXError):

    pass

class EncryptedWorkbookError(XLSXError):

    pass

def validate_xlsx_package(file_path: Union[str, Path]) -> None:

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    if not path.is_file():
        raise UnsupportedXLSXError(f"Target is not a regular file: {path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedXLSXError(
            f"Unsupported file extension '{ext}'. Only {sorted(SUPPORTED_EXTENSIONS)} are supported."
        )

    file_size = path.stat().st_size
    if file_size == 0:
        raise CorruptWorkbookError(f"File is empty (0 bytes): {path}")

    if file_size > MAX_FILE_SIZE_BYTES:
        raise UnsupportedXLSXError(
            f"File size {file_size} bytes exceeds maximum limit ({MAX_FILE_SIZE_BYTES} bytes)."
        )

    if ext in (".xlsx", ".xlsm", ".xltx", ".xltm"):
        with open(path, "rb") as f:
            header_bytes = f.read(8)
            if header_bytes == OLE_HEADER:
                raise EncryptedWorkbookError(
                    f"Workbook '{path.name}' is password-protected or encrypted; decryption is not supported."
                )

        try:
            with zipfile.ZipFile(path, "r") as zf:
                namelist = set(zf.namelist())

                if "[Content_Types].xml" not in namelist:
                    raise CorruptWorkbookError(
                        f"Corrupt XLSX package: missing '[Content_Types].xml' in {path.name}"
                    )
                if "xl/workbook.xml" not in namelist:
                    raise CorruptWorkbookError(
                        f"Corrupt XLSX package: missing 'xl/workbook.xml' in {path.name}"
                    )

                total_uncompressed = 0
                for info in zf.infolist():
                    total_uncompressed += info.file_size
                    if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                        raise UnsupportedXLSXError(
                            f"Uncompressed archive size exceeds limit ({MAX_UNCOMPRESSED_BYTES} bytes)."
                        )

                if file_size > 0 and (total_uncompressed / file_size) > MAX_COMPRESSION_RATIO:
                    raise UnsupportedXLSXError(
                        "Archive exhibits suspicious compression ratio exceeding safety threshold."
                    )
        except zipfile.BadZipFile as e:
            raise CorruptWorkbookError(f"Corrupt or invalid ZIP archive for '{path.name}': {e}")

    elif ext == ".ods":
        try:
            with zipfile.ZipFile(path, "r") as zf:
                namelist = set(zf.namelist())
                if "content.xml" not in namelist:
                    raise CorruptWorkbookError(f"Corrupt ODS package: missing 'content.xml' in {path.name}")
        except zipfile.BadZipFile as e:
            raise CorruptWorkbookError(f"Corrupt or invalid ZIP archive for '{path.name}': {e}")

    elif ext in (".xls", ".xlsb"):
        with open(path, "rb") as f:
            header = f.read(8)
            if ext == ".xls" and header != OLE_HEADER:
                raise CorruptWorkbookError(f"Invalid OLE Compound Document header in '{path.name}'")

def _convert_via_soffice(file_path: Path, target_ext: str = "xlsx") -> Optional[Tuple[Path, str]]:

    soffice_bin = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice_bin and os.name == "nt":
        for win_path in [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]:
            if os.path.exists(win_path):
                soffice_bin = win_path
                break
    if not soffice_bin:
        return None
    tmp_dir = tempfile.mkdtemp(prefix="xlsx_conv_")
    try:
        cmd = [soffice_bin, "--headless", "--convert-to", target_ext, str(file_path), "--outdir", tmp_dir]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if res.returncode == 0:
            converted = Path(tmp_dir) / f"{file_path.stem}.{target_ext}"
            if converted.exists():
                return converted, tmp_dir
    except Exception:
        pass
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return None

def _parse_ods_to_workbook(file_path: Path) -> Tuple[openpyxl.Workbook, openpyxl.Workbook]:

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            xml_data = zf.read("content.xml")
        root = etree.fromstring(xml_data)
        for table in root.iter("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table"):
            sname = table.attrib.get("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}name", "Sheet1")
            ws = wb.create_sheet(title=sname)
            r_idx = 1
            for row in table.iter("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row"):
                c_idx = 1
                for cell in row.iter("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell"):
                    txt = "".join(cell.itertext()).strip()
                    if txt:
                        ws.cell(row=r_idx, column=c_idx, value=txt)
                    c_idx += 1
                r_idx += 1
    except Exception as e:
        raise CorruptWorkbookError(f"Failed to parse ODS '{file_path.name}': {e}")
    if not wb.sheetnames:
        wb.create_sheet(title="Sheet1")
    return wb, wb

def _parse_xls_fallback_to_workbook(file_path: Path) -> Tuple[openpyxl.Workbook, openpyxl.Workbook]:

    with open(file_path, "rb") as f:
        data = f.read()

    # Skip 512-byte OLE compound file header if present to prevent binary header leakage
    if data.startswith(OLE_HEADER) and len(data) > 512:
        data = data[512:]

    cells: List[str] = []

    # 1. Attempt UTF-16LE runs (standard for binary Office streams)
    utf16_runs = re.findall(b"(?:[\x20-\x7e\xa0-\xff]\x00){3,}", data)
    for run in utf16_runs:
        try:
            txt = run.decode("utf-16le", errors="ignore").strip()
            if len(txt) > 2 and not any(txt.startswith(ign) for ign in ("Root", "Workbook", "SummaryInformation")):
                for line in txt.splitlines():
                    clean_line = "".join(ch for ch in line if ch.isprintable()).strip()
                    if len(clean_line) > 1 and clean_line not in cells:
                        cells.append(clean_line)
        except Exception:
            pass

    # 2. Capture printable ASCII runs, splitting cleanly without header artifacts
    ascii_runs = re.findall(b"[\x20-\x7e]{3,}", data)
    for r in ascii_runs:
        txt = r.decode("latin1", errors="ignore").strip()
        clean_txt = "".join(ch for ch in txt if ch.isprintable()).strip()
        if len(clean_txt) > 2 and not any(clean_txt.startswith(ign) for ign in ("Root", "Workbook", "SummaryInformation")):
            if clean_txt not in cells:
                cells.append(clean_txt)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for idx, c in enumerate(cells, start=1):
        ws.cell(row=idx, column=1, value=c)
    return wb, wb

def load_dual_workbooks(
    file_path: Union[str, Path],
    read_only: bool = False,
) -> Tuple[openpyxl.Workbook, openpyxl.Workbook]:

    path = Path(file_path).resolve()
    validate_xlsx_package(path)
    ext = path.suffix.lower()

    if ext in (".xlsx", ".xlsm", ".xltx", ".xltm"):
        try:
            wb_formula = openpyxl.load_workbook(
                str(path),
                data_only=False,
                read_only=read_only,
                keep_links=True,
            )
        except Exception as e:
            raise CorruptWorkbookError(f"Failed to load formula pass with openpyxl: {e}")

        try:
            wb_value = openpyxl.load_workbook(
                str(path),
                data_only=True,
                read_only=read_only,
                keep_links=True,
            )
        except Exception as e:
            wb_formula.close()
            raise CorruptWorkbookError(f"Failed to load value pass with openpyxl: {e}")

        return wb_formula, wb_value

    conv_result = _convert_via_soffice(path, target_ext="xlsx")
    if conv_result:
        conv_path, tmp_dir = conv_result
        try:
            wb_f = openpyxl.load_workbook(str(conv_path), data_only=False, read_only=read_only)
            wb_v = openpyxl.load_workbook(str(conv_path), data_only=True, read_only=read_only)
            return wb_f, wb_v
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if ext == ".ods":
        return _parse_ods_to_workbook(path)
    elif ext in (".xls", ".xlsb"):
        return _parse_xls_fallback_to_workbook(path)

    raise UnsupportedXLSXError(f"Unable to process spreadsheet '{path.name}'")

def get_true_sheet_dimensions(ws: Worksheet) -> Tuple[int, int, int, int]:

    min_row, max_row = None, None
    min_col, max_col = None, None

    if ws.max_row is None or ws.max_row == 0:
        return 1, 1, 1, 1

    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        has_content = any(c is not None and str(c).strip() != "" for c in row)
        if has_content:
            if min_row is None:
                min_row = row_idx
            max_row = row_idx

            for col_idx, cell_val in enumerate(row, start=1):
                if cell_val is not None and str(cell_val).strip() != "":
                    if min_col is None or col_idx < min_col:
                        min_col = col_idx
                    if max_col is None or col_idx > max_col:
                        max_col = col_idx

    if min_row is None:
        return 1, 1, 1, 1

    return min_row, max_row, (min_col or 1), (max_col or 1)

def _format_date(val: Any) -> Optional[str]:

    if isinstance(val, (datetime, date)):
        return val.isoformat()
    elif isinstance(val, str) and val.strip():
        return val.strip()
    return None

def extract_workbook_metadata(wb: openpyxl.Workbook) -> Metadata:

    meta = Metadata()
    props = getattr(wb, "properties", None)

    if props:
        meta.title = getattr(props, "title", None) or None
        meta.author = getattr(props, "creator", None) or None
        meta.description = getattr(props, "description", None) or getattr(props, "subject", None) or None
        meta.date = _format_date(getattr(props, "created", None)) or _format_date(getattr(props, "modified", None))
        meta.language = getattr(props, "language", None) or None

        extra: Dict[str, Any] = {}
        for attr in ("lastModifiedBy", "category", "keywords", "contentStatus", "version"):
            val = getattr(props, attr, None)
            if val is not None and str(val).strip():
                extra[attr] = str(val).strip()

        if getattr(props, "created", None):
            extra["created_at"] = _format_date(getattr(props, "created", None))
        if getattr(props, "modified", None):
            extra["modified_at"] = _format_date(getattr(props, "modified", None))

        meta.extra = extra

    sheets_info: List[Dict[str, Any]] = []
    for idx, sheet_name in enumerate(wb.sheetnames):
        ws = wb[sheet_name]
        state = getattr(ws, "sheet_state", "visible") or "visible"
        sheets_info.append({
            "index": idx,
            "name": sheet_name,
            "state": state,
            "is_visible": state == "visible",
        })

    meta.extra["sheets"] = sheets_info

    defined_names = []
    try:
        for name, def_name in getattr(wb, "defined_names", {}).items():
            destinations = getattr(def_name, "destinations", [])
            dests = [{"sheet": s, "range": r} for s, r in destinations] if destinations else []
            defined_names.append({
                "name": name,
                "value": getattr(def_name, "value", None),
                "destinations": dests,
            })
    except Exception:
        pass

    meta.extra["defined_names"] = defined_names
    return meta
