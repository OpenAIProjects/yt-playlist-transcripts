# yt-playlist-transcripts

[![CI](https://github.com/mattheogim/yt-playlist-transcripts/actions/workflows/ci.yml/badge.svg)](https://github.com/mattheogim/yt-playlist-transcripts/actions/workflows/ci.yml)

Extract every transcript in a YouTube playlist into clean, timestamped markdown.

One command per playlist. For each video you get a readable `.md` (grouped into
timestamped blocks, split on YouTube chapters when they exist) plus a
`.raw.json` sidecar preserving the original caption segments verbatim. A
`manifest.json` accounts for every video in the playlist — including the ones
that failed or had no captions — and a generated `README.md` indexes it all.

Backend: [yt-dlp](https://github.com/yt-dlp/yt-dlp). No YouTube API key needed.

## Status

- **Working.** Built for and used on an 86-video lecture playlist; every video
  accounted for, coverage verified with the built-in `verify` command.
- **Not on PyPI yet** — install from GitHub (below).
- Pre-1.0: CLI flags and output format may still change.
- YouTube rate-limits aggressive fetching. The tool downloads only the one
  caption track it needs per video, jitters between videos, retries with
  backoff, and records rate-limit failures in the manifest so you can resume.

## Quick start

With [pipx](https://pipx.pypa.io/) (recommended):

```bash
pipx install git+https://github.com/mattheogim/yt-playlist-transcripts.git

yt-playlist-transcripts "https://www.youtube.com/playlist?list=<PLAYLIST_ID>" --limit 3
```

`<PLAYLIST_ID>` is the `list=` parameter of any YouTube playlist URL. `--limit 3`
processes just the first 3 videos so you can check the output before committing
to a full run; drop it when you're happy.

Or from a clone:

```bash
git clone https://github.com/mattheogim/yt-playlist-transcripts.git
cd yt-playlist-transcripts
python3 -m venv .venv && .venv/bin/pip install -e .

.venv/bin/yt-playlist-transcripts "https://www.youtube.com/playlist?list=<PLAYLIST_ID>" --limit 3
```

Requires Python 3.10+.

Output goes to `./output/<playlist_id>/` by default (use `-o` to override):

```
output/<playlist_id>/
  README.md                 # generated index: counts + per-video status table
  manifest.json             # status for every playlist entry (resume state)
  01-<videoid>-<slug>.md    # readable transcript, timestamped blocks
  01-<videoid>-<slug>.raw.json  # original caption segments, verbatim
  02-...
```

## Example output

Each `.md` looks like this (shortened):

```markdown
---
video_id: aBcDeFgHiJk
title: Lecture 1 — Introduction
channel: Example Channel
duration_sec: 512
url: https://www.youtube.com/watch?v=aBcDeFgHiJk
playlist_index: 1
source: auto
language_code: en
is_generated: true
block_count: 9
segment_count: 214
---

# Lecture 1 — Introduction

**Channel**: Example Channel
**URL**: https://www.youtube.com/watch?v=aBcDeFgHiJk
**Source**: auto (en)

## Transcript

_Source: **auto** (en). 9 blocks, 214 raw segments. Sentence boundaries NOT
inferred — 75s max-block. Raw segments preserved in `01-aBcDeFgHiJk-lecture-1-introduction.raw.json`._

### [00:00]

welcome to the course in this first lecture we're going to define the basic
model and walk through a simple example so let's start with the setup ...

### [01:12]

now the key assumption here is that both players move at the same time ...
```

Videos with YouTube chapters get one block per chapter, with the chapter title
in the block header (`### [04:30] The Setup`).

## Commands

### `yt-playlist-transcripts <url>` (extract — the default)

| Flag | Meaning |
|------|---------|
| `-o, --output DIR` | Output directory (default `./output/<playlist_id>`) |
| `--langs en,ko` | Caption language priority; manual tracks beat auto tracks |
| `--limit N` | Process only the first N videos |
| `--start N` | Start at playlist index N (1-based) |
| `--force` | Overwrite existing `.md` files |
| `--delay-min` / `--delay-max` | Jitter between videos (default 0.5–2.0s) |

Re-running is safe: videos with an existing `.md` are skipped unless `--force`.

### `yt-playlist-transcripts regen <output_dir>`

Rebuild all `.md` files from their `.raw.json` sidecars without touching
YouTube — useful when the block-splitting logic changes.

### `yt-playlist-transcripts verify <output_dir>`

Coverage and structure checks: flags transcripts that end well before the
video's duration, chapter/block count mismatches, and word-count drift between
the raw segments and the rendered markdown. Exits non-zero if anything is
flagged.

## Channel research pipeline

`run.ps1`, `run.sh`, and `run_research.py` run the channel workflow: enumerate
the channel's `/videos` page, extract or resume transcripts, identify
transcripts without a summary, call `codex exec` once per video, update a
cross-video report, and write an index and failure list. The transcript
extractor's existing `manifest.json` remains the source of truth for extraction
status. The PowerShell and Bash scripts are convenient wrappers around the
Python runner. Each successful invocation prints the matching command syntax
and a short option guide before starting the workflow.

Requirements: Python 3.10+ with this project installed (`pip install -e .`),
and the Codex CLI available as `codex` on `PATH`.

PowerShell:

```powershell
.\run.ps1 -Channel "https://www.youtube.com/@example/videos"
```

For example, set a custom output folder and cap the run at five videos:

```powershell
.\run.ps1 -Channel "https://www.youtube.com/@example/videos" `
  -OutputDirectory ".\output\example" -Limit 5
```

Bash:

```bash
bash ./run.sh --channel "https://www.youtube.com/@example/videos"
```

The Bash wrapper accepts the same options as the Python runner:

```bash
bash ./run.sh --channel "https://www.youtube.com/@example/videos" \
  --output ./output/example --limit 5
```

Run the shared Python entry point directly when preferred:

```bash
python run_research.py --channel "https://www.youtube.com/@example/videos" \
  --output ./output/example --limit 5
```

PowerShell supports `-OutputDirectory`, `-Langs`, `-Limit`, `-DelayMin`,
`-DelayMax`, and `-Force`. The Bash wrapper and Python runner support `--output`,
`--langs`, `--limit`, `--delay-min`, `--delay-max`, and `--force`. Without an
explicit output directory, files go to `output/<channel-handle>/`. The pipeline
writes `INDEX.md`, `FAILURES.md`, `RESEARCH.md`, and individual summaries under
`summaries/`. Failed Codex summaries are retried on the next run; `-Force` /
`--force` re-extracts transcripts and regenerates summaries.

## How block splitting works

Sentence boundaries are **not** inferred for ASR text. Blocks split on:

- **Chapter starts** when YouTube chapters exist (usually the most useful boundary)
- **Pauses ≥ 2.5s** between cues (only for non-rolling sources — pause data is
  meaningless after rolling-dedup)
- **75s max-block** as a hard cap

YouTube auto-VTT uses a "rolling" pattern: each new line is delivered as a
zero-duration cue, then re-emitted in the next cue alongside the previous line
still on screen. The dedup keeps only the zero-duration cues, which carry each
fresh line exactly once.

## Design principles

1. **Preserve the original aggressively.** Not a single word is edited. Block
   grouping is the only transformation applied to the markdown body; raw
   segments stay in `.raw.json` for any future cleanup pass to diff against.
2. **Native captions only.** Manual creator-uploaded subtitles take priority.
   Auto-translated tracks (URL contains `tlang=`) are skipped — those are
   double-machine-processed and not the creator's voice.
3. **Account for every video.** The manifest records every playlist entry with
   one of 8 statuses (`done`, `skipped_no_transcript`, `skipped_existing`,
   `failed_*`). The generated index shows counts and a per-video table.
4. **Resume-friendly.** Re-running skips already-extracted videos; failures are
   recorded, not fatal.

Transcripts are creator content — `output/` is gitignored and stays local.

## License

[MIT](LICENSE)
