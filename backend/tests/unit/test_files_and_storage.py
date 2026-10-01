import uuid
from pathlib import Path

import pytest

from app.ingestion.filenames import extension, sanitise_filename
from app.storage import LocalStorage, StorageKeyError, document_key, page_image_key
from app.storage.base import document_prefix


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\Lecture 5.pdf", "Lecture 5.pdf"),
        ("notes\u202egpj.exe", "notesgpj.exe"),  # bidi override removed
        ("  week\t3\nslides.pptx ", "week 3 slides.pptx"),
        ("...", "upload"),
        ("", "upload"),
    ],
)
def test_filenames_are_display_safe(raw: str, expected: str) -> None:
    assert sanitise_filename(raw) == expected


def test_long_filenames_keep_their_extension() -> None:
    name = sanitise_filename("a" * 400 + ".pdf")
    assert len(name) <= 200
    assert extension(name) == "pdf"


async def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    user, doc = uuid.uuid4(), uuid.uuid4()
    key = document_key(user, doc)
    source = tmp_path / "upload"
    source.write_bytes(b"%PDF-1.7 test")

    await storage.put_file(key, source)
    await storage.put_bytes(page_image_key(user, doc, 3), b"png")

    assert await storage.exists(key)
    assert await storage.read_bytes(key) == b"%PDF-1.7 test"
    assert b"".join([c async for c in storage.stream(key, chunk_size=4)]) == b"%PDF-1.7 test"
    assert (await storage.local_path(key)).is_relative_to(tmp_path)

    await storage.delete_prefix(document_prefix(user, doc))
    assert not await storage.exists(key)


@pytest.mark.parametrize(
    "key",
    [
        "../outside",
        "users/../../etc/passwd",
        f"users/{uuid.uuid4()}/documents/{uuid.uuid4()}/../../x",
        f"users/{uuid.uuid4()}/documents/{uuid.uuid4()}/pages/0.png",
        "/absolute/original",
    ],
)
async def test_storage_refuses_keys_it_did_not_build(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path / "root")
    with pytest.raises(StorageKeyError):
        await storage.put_bytes(key, b"x")


async def test_delete_prefix_cannot_target_the_root(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "root")
    for prefix in ("", "users/", "../"):
        with pytest.raises(StorageKeyError):
            await storage.delete_prefix(prefix)
