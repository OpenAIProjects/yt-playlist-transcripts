#!/usr/bin/env python3
"""Run channel discovery, transcript extraction, Codex summaries, and research indexing."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def channel_folder(url: str) -> str:
    parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
    if parts and parts[-1].lower() == "videos":
        parts.pop()
    value = parts[-1].lstrip("@") if parts else "channel"
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value or "channel"


def load_manifest(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Transcript extractor did not create {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_codex(prompt: str, output_file: Path, cwd: Path) -> tuple[bool, str]:
    codex = shutil.which("codex")
    if not codex:
        return False, "codex executable was not found on PATH"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    command = [
        codex,
        "exec",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_file.resolve()),
        "-",
    ]
    result = subprocess.run(
        command,
        input=prompt,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or f"codex exec exited {result.returncode}").strip()
        return False, detail[-3000:]
    if not output_file.is_file() or not output_file.read_text(encoding="utf-8").strip():
        return False, "codex exec completed without writing a non-empty final response"
    return True, ""


def video_transcript_path(output: Path, video: dict) -> Path | None:
    filename = video.get("md_file")
    path = output / filename if filename else None
    return path if path and path.is_file() else None


def write_index(output: Path, manifest: dict, summaries: Path) -> None:
    playlist = manifest.get("playlist", {})
    videos = manifest.get("videos", {})
    lines = [
        f"# Research index: {playlist.get('title') or playlist.get('url') or 'Channel'}",
        "",
        f"- Channel: {playlist.get('url', '')}",
        f"- Videos discovered: {playlist.get('video_count', len(videos))}",
        f"- Video records in manifest: {len(videos)}",
        "",
        "| # | Video | Transcript | Summary | Status |",
        "|---:|---|---|---|---|",
    ]
    for video_id, video in sorted(videos.items(), key=lambda item: item[1].get("playlist_index", 0)):
        transcript = video_transcript_path(output, video)
        summary = summaries / f"{transcript.stem}.summary.md" if transcript else None
        title = (video.get("title") or video_id).replace("|", "\\|").replace("\n", " ")
        transcript_link = f"[transcript]({transcript.name})" if transcript else "—"
        summary_link = f"[{summary.name}](summaries/{summary.name})" if summary and summary.is_file() else "—"
        summary_status = "summary ready" if summary and summary.is_file() else "summary pending"
        lines.append(
            f"| {video.get('playlist_index', '')} | [{title}]({video.get('url', '')}) | "
            f"{transcript_link} | {summary_link} | {video.get('status', 'unknown')}; {summary_status} |"
        )
    (output / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_failures(output: Path, manifest: dict, errors: list[tuple[str, str]]) -> None:
    lines = ["# Failures", "", "Extraction failures recorded in the manifest and failures from this run.", ""]
    failures = []
    for video_id, video in manifest.get("videos", {}).items():
        status = video.get("status", "unknown")
        if status.startswith("failed_") or status == "skipped_no_transcript":
            failures.append((video.get("playlist_index", ""), video.get("title") or video_id, status, video.get("error", "")))
    for name, detail in errors:
        failures.append(("", name, "summary_failed", detail))
    failures.sort(key=lambda row: (row[0] if isinstance(row[0], int) else 10**12, str(row[1])))
    if not failures:
        lines.append("No failures recorded.")
    else:
        lines.extend(["| # | Video | Status | Details |", "|---:|---|---|---|"])
        for index, title, status, detail in failures:
            safe = str(detail).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {index} | {title} | {status} | {safe} |")
    (output / "FAILURES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True, help="YouTube channel /videos URL")
    parser.add_argument("--output", type=Path, help="Output folder (default: output/<channel>)")
    parser.add_argument("--langs", default="en,ko", help="Caption language priority")
    parser.add_argument("--limit", type=int, help="Process only the first N videos")
    parser.add_argument("--delay-min", type=float, default=0.5)
    parser.add_argument("--delay-max", type=float, default=2.0)
    parser.add_argument("--force", action="store_true", help="Re-extract transcripts and regenerate summaries")
    args = parser.parse_args()

    launcher = os.environ.get("YT_RESEARCH_LAUNCHER")
    if launcher == "powershell":
        usage = r"Usage: .\run.ps1 -Channel <channel-url> [-OutputDirectory <dir>] [-Langs en,ko] [-Limit N] [-Force]"
    elif launcher == "bash":
        usage = "Usage: bash ./run.sh --channel <channel-url> [--output DIR] [--langs en,ko] [--limit N] [--force]"
    else:
        usage = "Usage: python run_research.py --channel <channel-url> [--output DIR] [--langs en,ko] [--limit N] [--force]"
    print(usage, flush=True)
    print("Options: --output sets the result folder; --langs sets subtitle language priority; --limit caps videos; --force re-extracts and regenerates summaries.", flush=True)

    root = Path(__file__).resolve().parent
    output = (args.output or (root / "output" / channel_folder(args.channel))).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    summaries = output / "summaries"

    print(f"[1/6] Discovering channel videos and extracting transcripts: {args.channel}", flush=True)
    command = [
        sys.executable,
        "-m",
        "yt_playlist_transcripts",
        args.channel,
        "--output",
        str(output),
        "--langs",
        args.langs,
        "--delay-min",
        str(args.delay_min),
        "--delay-max",
        str(args.delay_max),
    ]
    if args.limit:
        command.extend(["--limit", str(args.limit)])
    if args.force:
        command.append("--force")
    try:
        extracted = subprocess.run(command, cwd=root, check=False)
    except OSError as exc:
        print(f"Could not start transcript extractor: {exc}", file=sys.stderr)
        return 1
    pipeline_errors: list[tuple[str, str]] = []
    if extracted.returncode:
        pipeline_errors.append(("transcript extraction", f"Extractor exited with code {extracted.returncode}"))
        print(f"Transcript extraction exited with code {extracted.returncode}; continuing with the manifest.", file=sys.stderr)

    try:
        manifest = load_manifest(output / "manifest.json")
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return extracted.returncode or 1

    videos = manifest.get("videos", {})
    print(f"[2/6] Found {len(videos)} video records; checking for new transcript summaries.", flush=True)
    errors = pipeline_errors
    candidates = []
    for video_id, video in sorted(videos.items(), key=lambda item: item[1].get("playlist_index", 0)):
        transcript = video_transcript_path(output, video)
        if transcript is None:
            continue
        summary = summaries / f"{transcript.stem}.summary.md"
        if args.force or not summary.is_file():
            candidates.append((video_id, video, transcript, summary))

    print(f"[3/6] {len(candidates)} transcript(s) need an independent summary.", flush=True)
    for number, (video_id, video, transcript, summary) in enumerate(candidates, 1):
        print(f"[4/6] Summarizing {number}/{len(candidates)}: {video.get('title') or video_id}", flush=True)
        if args.force:
            summary.unlink(missing_ok=True)
        prompt = f"""Read the complete transcript file at `{transcript.name}` in the current directory and write an independent summary of this one video.

Video title: {video.get('title') or video_id}
Video URL: {video.get('url', '')}

Write a concise Markdown summary with: a one-paragraph overview; the main points in order; named people, organizations, places, dates, and figures; notable claims clearly attributed to the speaker; and unresolved or unclear points. Preserve the transcript's language. Separate what the speaker says from your interpretation. Do not use outside sources or invent details. Save the final response to the requested output file through the codex exec output option."""
        ok, error = run_codex(prompt, summary, output)
        error_file = summaries / f"{transcript.stem}.error.txt"
        if ok:
            error_file.unlink(missing_ok=True)
        else:
            summary.unlink(missing_ok=True)
            errors.append((video.get("title") or video_id, error))
            summaries.mkdir(parents=True, exist_ok=True)
            error_file.write_text(error + "\n", encoding="utf-8")
            print(f"  summary failed: {error}", file=sys.stderr)

    ready = [p for p in summaries.glob("*.summary.md") if p.is_file()] if summaries.exists() else []
    report = output / "RESEARCH.md"
    if ready:
        print(f"[5/6] Updating cross-video research report from {len(ready)} summary file(s).", flush=True)
        summary_names = "\n".join(f"- summaries/{p.name}" for p in sorted(ready))
        prior_note = f"Read the current report at `{report.name}` and update it without losing prior findings. " if report.is_file() else "Create a new report. "
        prompt = f"""{prior_note}Read and synthesize every individual video summary listed below into a cross-video research report. The current directory contains these files:
{summary_names}

Identify recurring themes, actors, positions, supporting examples, changes over time when dates permit, and meaningful disagreements or gaps. Distinguish reported claims from established facts; this task does not include external fact-checking. Include a short executive overview, thematic sections, a dated timeline when supported, and source links to the individual summaries using their listed relative paths. Keep uncertainty explicit. Do not invent connections unsupported by the summaries."""
        ok, error = run_codex(prompt, report, output)
        if not ok:
            errors.append(("cross-video research report", error))
            (output / "RESEARCH.error.txt").write_text(error + "\n", encoding="utf-8")
            print(f"Research report update failed: {error}", file=sys.stderr)
        else:
            (output / "RESEARCH.error.txt").unlink(missing_ok=True)
    else:
        print("[5/6] No summaries are available; skipping cross-video report.", flush=True)

    print("[6/6] Writing index and failure list.", flush=True)
    write_index(output, manifest, summaries)
    write_failures(output, manifest, errors)
    print(f"Index:    {output / 'INDEX.md'}")
    print(f"Failures: {output / 'FAILURES.md'}")
    if report.is_file():
        print(f"Research: {report}")
    return 1 if errors else extracted.returncode


if __name__ == "__main__":
    sys.exit(main())
