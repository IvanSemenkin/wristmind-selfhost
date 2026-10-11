"""Direct search inside this chat's saved documents.

A saved document is often much larger than the retrieval budget, so chunk
ranking alone can miss a specific task or clause. These checks cover the direct
text search: which document is chosen, what window is shown, and that the scan
stays bounded when a chat has many saved sources.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from wristmind_server.worker import saved_source_window

FILLER = "## Страница 1\n" + ("общие сведения про климат, погоду и природу. " * 300)
TASK = FILLER + "\n## Страница 12\nЗадача 12. Бревно плавает в воде.\nНайти плотность.\n"

SETTINGS = {"max_chars": 6_000, "scan_limit": 5, "strong_score": 40.0}


def _source(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return SimpleNamespace(
        id=name, title=name, storage_path=str(path), source_tier="working",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_the_window_comes_from_the_document_that_matches(tmp_path):
    other = _source(tmp_path, "other.txt", FILLER)
    wanted = _source(tmp_path, "wanted.txt", TASK)

    result = saved_source_window([other, wanted], "задача 12 про бревно", **SETTINGS)

    assert result is not None
    source, window, page = result
    assert source.id == "wanted.txt"
    assert "Бревно плавает" in window
    assert page == "12"
    assert len(window) <= SETTINGS["max_chars"]


def test_a_question_that_matches_nothing_shows_nothing(tmp_path):
    source = _source(tmp_path, "other.txt", FILLER)

    assert saved_source_window([source], "задача 12", **SETTINGS) is None
    assert saved_source_window([], "задача 12", **SETTINGS) is None


def test_the_scan_is_bounded_by_the_limit(tmp_path):
    filler = [_source(tmp_path, f"f{index}.txt", FILLER) for index in range(2)]
    wanted = _source(tmp_path, "wanted.txt", TASK)

    # The matching document is last: with two scanned it is never reached.
    assert saved_source_window(filler + [wanted], "задача 12", **{**SETTINGS, "scan_limit": 2}) is None
    assert saved_source_window(filler + [wanted], "задача 12", **{**SETTINGS, "scan_limit": 3}) is not None


def test_an_unreadable_document_is_skipped(tmp_path):
    broken = SimpleNamespace(
        id="broken", title="broken", storage_path=str(tmp_path / "missing.txt"),
        source_tier="working", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert saved_source_window([broken], "задача 12", **SETTINGS) is None
