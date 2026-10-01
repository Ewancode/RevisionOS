"""Upload validation: the bytes decide the type (ARCHITECTURE.md sections 12-13)."""

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import UploadsConfig, get_config
from app.core.errors import AppError
from app.ingestion.validation import Kind, validate_upload
from tests import factories

CONFIG = get_config().platform.uploads


def _config(**changes: object) -> UploadsConfig:
    return CONFIG.model_copy(update=changes)


def _expect(code: str, path: Path, ext: str, config: UploadsConfig = CONFIG) -> AppError:
    with pytest.raises(AppError) as exc_info:
        validate_upload(path, ext, config)
    assert exc_info.value.code == code
    return exc_info.value


def test_valid_pdf(tmp_path: Path) -> None:
    result = validate_upload(factories.pdf(tmp_path / "a", ["one", "two"]), "pdf", CONFIG)
    assert (result.kind, result.mime, result.page_count) == (Kind.PDF, "application/pdf", 2)
    assert len(result.sha256) == 32


@pytest.mark.parametrize("ext", ["png", "docx", "txt"])
def test_pdf_disguised_as_another_type_is_rejected(tmp_path: Path, ext: str) -> None:
    _expect("type_mismatch", factories.pdf(tmp_path / "a"), ext)


def test_image_disguised_as_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a"
    Image.new("RGB", (4, 4)).save(path, "PNG")
    _expect("type_mismatch", path, "pdf")


def test_executable_renamed_to_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a"
    path.write_bytes(b"MZ\x90\x00" + b"\x00" * 200)
    _expect("type_mismatch", path, "pdf")


def test_unknown_extension_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a"
    path.write_bytes(b"MZ")
    error = _expect("unsupported_type", path, "exe")
    assert ".pdf" in error.message


def test_binary_in_text_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a"
    path.write_bytes(b"hello\x00world")
    _expect("type_mismatch", path, "txt")


def test_non_utf8_text_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a"
    path.write_bytes("café".encode("latin-1"))
    _expect("text_not_utf8", path, "md")


def test_empty_and_oversized_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    _expect("file_empty", empty, "txt")

    big = tmp_path / "big"
    big.write_bytes(b"a" * (2 * 1024 * 1024))
    small = _config(max_megabytes=CONFIG.max_megabytes.model_copy(update={"text": 1}))
    error = _expect("file_too_large", big, "txt", small)
    assert error.status_code == 413


def test_word_document_is_recognised(tmp_path: Path) -> None:
    result = validate_upload(factories.docx(tmp_path / "a", "# Hello"), "docx", CONFIG)
    assert result.kind is Kind.DOCX


def test_word_document_renamed_to_pptx_is_rejected(tmp_path: Path) -> None:
    _expect("type_mismatch", factories.docx(tmp_path / "a", "# Hello"), "pptx")


def test_macros_are_rejected(tmp_path: Path) -> None:
    clean = factories.docx(tmp_path / "clean", "# Hello")
    infected = factories.with_extra_zip_entry(clean, tmp_path / "m", "word/vbaProject.bin", b"x")
    _expect("macro_not_allowed", infected, "docx")


def test_zip_bombs_are_rejected(tmp_path: Path) -> None:
    clean = factories.docx(tmp_path / "clean", "# Hello")
    bomb = factories.with_extra_zip_entry(
        clean, tmp_path / "b", "word/padding.bin", b"\0" * 20_000_000
    )
    _expect("archive_suspicious", bomb, "docx")


def test_plain_zip_is_not_an_office_file(tmp_path: Path) -> None:
    path = tmp_path / "a"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("notes.txt", "hi")
    _expect("unsupported_type", path, "docx")


def test_encrypted_pdf_is_rejected(tmp_path: Path) -> None:
    _expect("file_encrypted", factories.encrypted_pdf(tmp_path / "a"), "pdf")


def test_too_many_pages(tmp_path: Path) -> None:
    _expect(
        "too_many_pages", factories.pdf(tmp_path / "a", ["x"] * 3), "pdf", _config(max_pdf_pages=2)
    )


def test_photos_lose_their_metadata_but_keep_their_orientation(tmp_path: Path) -> None:
    path = factories.jpeg_with_gps(tmp_path / "photo")
    with Image.open(path) as before:
        assert before.getexif().get(0x8825)

    result = validate_upload(path, "jpg", CONFIG)

    assert result.kind is Kind.JPEG
    with Image.open(io.BytesIO(path.read_bytes())) as after:
        assert not after.getexif()  # GPS and everything else gone
        assert after.size == (20, 40)  # the camera rotation was applied


def test_decompression_bombs_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a"
    Image.new("L", (300, 300)).save(path, "PNG")
    _expect("image_too_large", path, "png", _config(max_image_pixels=10_000))
