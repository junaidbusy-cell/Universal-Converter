
import hashlib
import mimetypes
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

class EPUBAssetManager:

    def __init__(self, asset_dir: Optional[Union[str, Path]] = None):
        self.asset_dir = Path(asset_dir) if asset_dir else None
        self._hash_cache: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        self._image_counter = 1

    def ensure_asset_dir(self) -> Optional[Path]:
        if self.asset_dir:
            self.asset_dir.mkdir(parents=True, exist_ok=True)
        return self.asset_dir

    def extract_image_bytes(
        self,
        image_bytes: bytes,
        original_path: str,
        alt_text: str = "",
        relative_prefix: str = "assets",
        is_cover: bool = False,
    ) -> Optional[Dict[str, Any]]:

        if not image_bytes:
            return None

        sha256 = hashlib.sha256(image_bytes).hexdigest()

        if sha256 in self._hash_cache:
            rel_path, cached_dict = self._hash_cache[sha256]
            res = dict(cached_dict)
            if alt_text:
                res["alt_text"] = alt_text
            if is_cover:
                res["is_cover"] = True
            return res

        ext = Path(original_path).suffix.lower()
        if not ext or ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"):
            ext = ".png"
        elif ext == ".jpeg":
            ext = ".jpg"

        if is_cover:
            filename = f"cover{ext}"
        else:
            filename = f"image_{self._image_counter:03d}{ext}"
            self._image_counter += 1

        rel_path = f"{relative_prefix}/{filename}" if relative_prefix else filename
        abs_path = None

        if self.asset_dir:
            self.ensure_asset_dir()
            out_file = self.asset_dir / filename
            try:
                out_file.write_bytes(image_bytes)
                abs_path = str(out_file)
            except Exception:
                pass

        img_dict = {
            "name": filename,
            "path": rel_path,
            "absolute_path": abs_path,
            "original_path": original_path,
            "sha256": sha256,
            "size_bytes": len(image_bytes),
            "alt_text": alt_text,
            "is_cover": is_cover,
        }

        self._hash_cache[sha256] = (rel_path, img_dict)
        return img_dict

    def extract_archive_image(
        self,
        zf: zipfile.ZipFile,
        full_path: str,
        alt_text: str = "",
        is_cover: bool = False,
    ) -> Optional[Dict[str, Any]]:

        try:
            if full_path not in set(zf.namelist()):
                return None
            image_bytes = zf.read(full_path)
            return self.extract_image_bytes(
                image_bytes=image_bytes,
                original_path=full_path,
                alt_text=alt_text,
                is_cover=is_cover,
            )
        except Exception:
            return None
