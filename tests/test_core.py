"""Unit tests for the pure transcript-processing functions (no network)."""

from yt_playlist_transcripts.extract import (
    clean_cue_text,
    dedup_rolling,
    fmt_ts,
    is_rolling_caption,
    make_blocks,
)


def seg(start: float, end: float, text: str) -> dict:
    return {"start_sec": start, "end_sec": end, "text": text}


def test_clean_cue_text_strips_inline_timestamps_tags_entities():
    raw = "hello<00:00:01.500><c> world</c> &amp; friends"
    assert clean_cue_text(raw) == "hello world & friends"


def test_clean_cue_text_collapses_whitespace():
    assert clean_cue_text("  a \n b\t c  ") == "a b c"


def test_fmt_ts():
    assert fmt_ts(0) == "00:00"
    assert fmt_ts(65) == "01:05"
    assert fmt_ts(3661) == "01:01:01"


def _rolling_segments(n: int = 10) -> list[dict]:
    """Simulate YouTube auto-VTT rolling pattern: zero-duration cue with fresh
    text, followed by a display cue that re-shows it."""
    segs = []
    for i in range(n):
        segs.append(seg(i, i, f"line {i}"))
        segs.append(seg(i, i + 1, f"line {i} redisplayed"))
    return segs


def test_rolling_caption_detected():
    assert is_rolling_caption(_rolling_segments())


def test_non_rolling_caption_not_detected():
    segs = [seg(i, i + 1, f"line {i}") for i in range(10)]
    assert not is_rolling_caption(segs)


def test_dedup_rolling_keeps_only_zero_duration_cues():
    kept = dedup_rolling(_rolling_segments(8))
    assert len(kept) == 8
    assert all(s["start_sec"] >= s["end_sec"] for s in kept)


def test_dedup_rolling_passthrough_without_zero_duration_cues():
    segs = [seg(0, 1, "a"), seg(1, 2, "b")]
    assert dedup_rolling(segs) == segs


def test_make_blocks_splits_on_pause():
    segs = [seg(0, 2, "a"), seg(2.5, 4, "b"), seg(10, 12, "c")]  # 6s gap before c
    blocks = make_blocks(segs)
    assert len(blocks) == 2
    assert blocks[0]["lines"] == ["a", "b"]
    assert blocks[1]["lines"] == ["c"]


def test_make_blocks_one_block_per_chapter():
    segs = [
        seg(0, 5, "intro a"),
        seg(5, 10, "intro b"),
        seg(60, 65, "body a"),
        seg(70, 75, "body b"),
    ]
    chapters = [
        {"start_time": 0, "title": "Intro"},
        {"start_time": 60, "title": "Body"},
    ]
    blocks = make_blocks(segs, chapters=chapters)
    assert [b["chapter"] for b in blocks] == ["Intro", "Body"]
    assert blocks[0]["lines"] == ["intro a", "intro b"]
    assert blocks[1]["lines"] == ["body a", "body b"]


def test_make_blocks_empty_input():
    assert make_blocks([]) == []
