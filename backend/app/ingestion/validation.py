"""Upload validation (ARCHITECTURE.md section 12, "File type" / "File structure").

The file's bytes decide its type; the extension must agree. Office
documents are zip archives and are checked for bombs, encryption and macros.
PDFs must open and fit the page limit. Images are decoded under a pixel
limit and re-encoded, which drops EXIF metadata such as phone GPS location.
"""

import hashlib
import io
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import UploadsConfig
from app.core.errors import AppError

MB = 1024 * 1024


class Kind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    CSV = "csv"
    TEXT = "text"
    MARKDOWN = "markdown"
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    HEIC = "heic"


MIME = {
    Kind.PDF: "application/pdf",
    Kind.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    Kind.PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    Kind.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    Kind.CSV: "text/csv",
    Kind.TEXT: "text/plain",
    Kind.MARKDOWN: "text/markdown",
    Kind.PNG: "image/png",
    Kind.JPEG: "image/jpeg",
}

# Extension -> the kind its bytes must turn out to be.
EXTENSIONS: dict[str, Kind] = {
    "pdf": Kind.PDF,
    "docx": Kind.DOCX,
    "pptx": Kind.PPTX,
    "xlsx": Kind.XLSX,
    "csv": Kind.CSV,
    "txt": Kind.TEXT,
    "md": Kind.MARKDOWN,
    "markdown": Kind.MARKDOWN,
    "png": Kind.PNG,
    "jpg": Kind.JPEG,
    "jpeg": Kind.JPEG,
    "webp": Kind.WEBP,
    "heic": Kind.HEIC,
    "heif": Kind.HEIC,
}
TEXT_KINDS = {Kind.CSV, Kind.TEXT, Kind.MARKDOWN}
IMAGE_KINDS = {Kind.PNG, Kind.JPEG, Kind.WEBP, Kind.HEIC}
OFFICE_KINDS = {Kind.DOCX, Kind.PPTX, Kind.XLSX}
HEIC_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"mif1", b"msf1"}
OFFICE_MAIN_PART = {
    "word/document.xml": Kind.DOCX,
    "ppt/presentation.xml": Kind.PPTX,
    "xl/workbook.xml": Kind.XLSX,
}


@dataclass(frozen=True)
class ValidatedFile:
    kind: Kind
    mime: str
    path: Path
    size_bytes: int
    sha256: bytes
    page_count: int | None = None


def reject(code: str, message: str, status: int = 422) -> AppError:
    return AppError(code, message, status)


def size_limit_bytes(kind: Kind, config: UploadsConfig) -> int:
    sizes = config.max_megabytes
    if kind is Kind.PDF:
        return sizes.pdf * MB
    if kind in OFFICE_KINDS:
        return sizes.office * MB
    if kind in IMAGE_KINDS:
        return sizes.image * MB
    return sizes.text * MB


def expected_kind(ext: str) -> Kind:
    kind = EXTENSIONS.get(ext)
    if kind is None:
        allowed = ", ".join(sorted({f".{e}" for e in EXTENSIONS}))
        raise reject("unsupported_type", f"That file type is not supported. Use one of: {allowed}.")
    return kind


def sniff(head: bytes) -> Kind | None:
    """Identify binary formats from leading bytes; None means 'not one of them'."""
    if b"%PDF-" in head[:1024]:
        return Kind.PDF
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Kind.PNG
    if head.startswith(b"\xff\xd8\xff"):
        return Kind.JPEG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return Kind.WEBP
    if head[4:8] == b"ftyp" and head[8:12] in HEIC_BRANDS:
        return Kind.HEIC
    if head.startswith(b"PK\x03\x04"):
        return Kind.DOCX  # some Office format; refined by _office_kind
    return None


def _office_kind(path: Path, config: UploadsConfig) -> Kind:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise reject("file_corrupt", "That Office file appears to be damaged.") from exc
    with archive:
        entries = archive.infolist()
        if len(entries) > config.zip_max_entries:
            raise reject("archive_suspicious", "That file contains too many internal parts.")
        total = sum(e.file_size for e in entries)
        compressed = sum(e.compress_size for e in entries) or 1
        if total > config.zip_max_uncompressed_megabytes * MB:
            raise reject("archive_suspicious", "That file expands to an unreasonable size.")
        if total / compressed > config.zip_max_compression_ratio:
            raise reject("archive_suspicious", "That file is compressed suspiciously heavily.")
        if any(e.flag_bits & 0x1 for e in entries):
            raise reject("file_encrypted", "Password-protected files cannot be processed.")
        names = {e.filename for e in entries}
        content_types = (
            archive.read("[Content_Types].xml").decode("utf-8", "replace")
            if "[Content_Types].xml" in names
            else ""
        )
    if any(n.lower().endswith("vbaproject.bin") for n in names) or "macroEnabled" in content_types:
        raise reject("macro_not_allowed", "Files containing macros are not accepted.")
    for part, kind in OFFICE_MAIN_PART.items():
        if part in names:
            return kind
    raise reject("unsupported_type", "That archive is not a Word, PowerPoint or Excel file.")


def _check_text(path: Path) -> None:
    data = path.read_bytes()
    if b"\x00" in data:
        raise reject("type_mismatch", "That file contains binary data, not text.")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise reject(
            "text_not_utf8", "Text files must be UTF-8. Re-save it as UTF-8 and retry."
        ) from exc


def _check_pdf(path: Path, config: UploadsConfig) -> int:
    try:
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                raise reject("file_encrypted", "Password-protected PDFs cannot be processed.")
            pages = int(doc.page_count)
    except AppError:
        raise
    except Exception as exc:
        raise reject("file_corrupt", "That PDF could not be read.") from exc
    if pages == 0:
        raise reject("file_empty", "That PDF has no pages.")
    if pages > config.max_pdf_pages:
        raise reject("too_many_pages", f"PDFs are limited to {config.max_pdf_pages} pages.")
    return pages


def _reencode_image(path: Path, kind: Kind, config: UploadsConfig) -> Kind:
    """Decode under a pixel limit and re-encode without metadata.

    HEIC and WebP become JPEG and PNG respectively: formats every browser
    shows and the vision API accepts.
    """
    if kind is Kind.HEIC:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    Image.MAX_IMAGE_PIXELS = config.max_image_pixels
    try:
        with Image.open(path) as img:
            if img.width * img.height > config.max_image_pixels:
                raise reject("image_too_large", "That image has too many pixels.")
            img.load()
            # Bake in the camera's rotation, then drop all metadata.
            upright = ImageOps.exif_transpose(img)
    except AppError:
        raise
    except Image.DecompressionBombError as exc:
        raise reject("image_too_large", "That image has too many pixels.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise reject("image_unreadable", "That image could not be read.") from exc

    out_kind = Kind.JPEG if kind in (Kind.JPEG, Kind.HEIC) else Kind.PNG
    buffer = io.BytesIO()
    if out_kind is Kind.JPEG:
        upright.convert("RGB").save(buffer, "JPEG", quality=92, optimize=True)
    else:
        mode = "RGBA" if upright.mode in ("RGBA", "LA", "P") else "RGB"
        upright.convert(mode).save(buffer, "PNG", optimize=True)
    path.write_bytes(buffer.getvalue())
    return out_kind


def _sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.digest()


def validate_upload(path: Path, ext: str, config: UploadsConfig) -> ValidatedFile:
    """Validate (and for images, rewrite) the file at `path`. Raises AppError."""
    expected = expected_kind(ext)
    size = path.stat().st_size
    if size == 0:
        raise reject("file_empty", "That file is empty.")
    limit = size_limit_bytes(expected, config)
    if size > limit:
        raise reject("file_too_large", f"Files of this type are limited to {limit // MB} MB.", 413)

    with path.open("rb") as handle:
        head = handle.read(2048)
    detected = sniff(head)
    if detected is Kind.DOCX:
        detected = _office_kind(path, config)

    page_count: int | None = None
    if expected in TEXT_KINDS:
        if detected is not None:
            raise reject("type_mismatch", "That file's contents do not match its extension.")
        _check_text(path)
        kind = expected
    else:
        if detected is not expected:
            raise reject("type_mismatch", "That file's contents do not match its extension.")
        kind = expected
        if kind is Kind.PDF:
            page_count = _check_pdf(path, config)
        elif kind in IMAGE_KINDS:
            kind = _reencode_image(path, kind, config)
            page_count = 1

    return ValidatedFile(
        kind=kind,
        mime=MIME[kind],
        path=path,
        size_bytes=path.stat().st_size,
        sha256=_sha256(path),
        page_count=page_count,
    )
