import uuid
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from app.ingestion.filenames import extension, sanitise_filename
from app.storage import LocalStorage, S3Storage, StorageKeyError, document_key, page_image_key
from app.storage.base import StorageBackend, archive_key, document_prefix


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


@pytest.fixture(params=["local", "s3"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[StorageBackend]:
    """Both backends must behave the same (S3 against moto's in-memory fake)."""
    if request.param == "local":
        yield LocalStorage(tmp_path / "root")
        return
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-2")
        client.create_bucket(
            Bucket="revision-os",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-2"},
        )
        yield S3Storage("revision-os", client=client)


async def test_storage_round_trip(storage: StorageBackend, tmp_path: Path) -> None:
    user, doc = uuid.uuid4(), uuid.uuid4()
    key = document_key(user, doc)
    source = tmp_path / "upload"
    source.write_bytes(b"%PDF-1.7 test")

    await storage.put_file(key, source)
    await storage.put_bytes(page_image_key(user, doc, 3), b"png")
    export = archive_key(user, uuid.uuid4(), "export")
    await storage.put_bytes(export, b"zip")

    assert await storage.exists(key)
    assert not await storage.exists(document_key(user, uuid.uuid4()))
    assert await storage.read_bytes(key) == b"%PDF-1.7 test"
    assert b"".join([c async for c in storage.stream(key, chunk_size=4)]) == b"%PDF-1.7 test"
    async with storage.local_copy(key) as path:
        assert path.read_bytes() == b"%PDF-1.7 test"
    assert sorted(await storage.list_keys(f"users/{user}/")) == sorted(
        [key, page_image_key(user, doc, 3), export]
    )
    assert await storage.list_keys(f"users/{uuid.uuid4()}/") == []

    await storage.delete(export)
    await storage.delete(export)  # already gone: not an error
    await storage.delete_prefix(document_prefix(user, doc))
    assert not await storage.exists(key)
    assert await storage.list_keys(f"users/{user}/") == []


@pytest.mark.parametrize(
    "key",
    [
        "../outside",
        "users/../../etc/passwd",
        f"users/{uuid.uuid4()}/documents/{uuid.uuid4()}/../../x",
        f"users/{uuid.uuid4()}/documents/{uuid.uuid4()}/pages/0.png",
        f"users/{uuid.uuid4()}/exports/x.zip",
        "/absolute/original",
    ],
)
async def test_storage_refuses_keys_it_did_not_build(storage: StorageBackend, key: str) -> None:
    with pytest.raises(StorageKeyError):
        await storage.put_bytes(key, b"x")


async def test_prefixes_cannot_target_the_root(storage: StorageBackend) -> None:
    for prefix in ("", "users/", "../"):
        with pytest.raises(StorageKeyError):
            await storage.delete_prefix(prefix)
        with pytest.raises(StorageKeyError):
            await storage.list_keys(prefix)
