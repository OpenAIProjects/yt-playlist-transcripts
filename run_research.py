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

from yt_playlist_transcripts.date_utils import parse_since, parse_upload_date
from yt_playlist_transcripts.progress import ProgressBar, Spinner


def channel_folder(url: str) -> str:
    parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
    if parts and parts[-1].lower() == "videos":
        parts.pop()
    value = parts[-1] if parts else "channel"
    if value.startswith("@"):
        handle = re.sub(r"[^A-Za-z0-9._-]+", "-", value[1:]).strip("-._")
        return f"@{handle}" if handle else "channel"
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value or "channel"


def normalize_channel(value: str) -> str:
    """Expand a YouTube @handle shorthand into its channel videos URL."""
    value = value.strip()
    if value.startswith("@"):
        handle = value.strip("/")
        if any(character.isspace() for character in handle):
            raise ValueError(
                "YouTube handles cannot contain spaces. Pass the exact @handle "
                "(for example, @tomnashtv) or the channel's /videos URL."
            )
        return f"https://www.youtube.com/{handle}/videos"
    return value


def normalize_long_options(argv: list[str]) -> list[str]:
    """Make GNU-style long option names case-insensitive, preserving values."""
    normalized = []
    for token in argv:
        if token.startswith("--"):
            option, separator, value = token.partition("=")
            token = option.lower() + separator + value
        normalized.append(token)
    return normalized


def translation_language_slug(language: str) -> str:
    return re.sub(r"[^\w.-]+", "-", language.strip(), flags=re.UNICODE).strip("-._")


def print_command_usage(launcher: str | None) -> None:
    if launcher == "powershell":
        usage = r"Usage: .\run.ps1 -Channel <channel-url|@handle> [-Since <YYYY-MM-DD|-1|0>] [-OutputDirectory <dir>] [-Limit N] [-TranslateTo LANGUAGE] [-Force]"
        options = "Options: -Since filters inclusively by upload date; -1 means yesterday and 0 means today. -OutputDirectory sets the result folder; -Langs sets caption priority; -Limit caps videos; -TranslateTo creates translated transcript copies; -Force re-extracts and regenerates outputs."
    elif launcher == "bash":
        usage = "Usage: bash ./run.sh --channel <channel-url|@handle> [--since YYYY-MM-DD|-1|0] [--output DIR] [--limit N] [--translate-to LANGUAGE] [--force]"
        options = "Options: --since filters inclusively by upload date; -1 means yesterday and 0 means today. --output sets the result folder; --langs sets caption priority; --limit caps videos; --translate-to creates translated transcript copies; --force re-extracts and regenerates outputs."
    else:
        usage = "Usage: python run_research.py --channel <channel-url|@handle> [--since YYYY-MM-DD|-1|0] [--output DIR] [--limit N] [--translate-to LANGUAGE] [--force]"
        options = "Options: --since filters inclusively by upload date; -1 means yesterday and 0 means today. --output sets the result folder; --langs sets caption priority; --limit caps videos; --translate-to creates translated transcript copies; --force re-extracts and regenerates outputs."
    print(usage, flush=True)
    print(options, flush=True)


def save_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


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


def transcript_upload_date(video: dict, transcript: Path):
    uploaded = parse_upload_date(video)
    if uploaded is not None:
        return uploaded
    try:
        header = transcript.read_text(encoding="utf-8")[:4000]
    except OSError:
        return None
    match = re.search(r"(?m)^upload_date:\s*[\"']?([^\"'\\s]+)", header)
    return parse_upload_date({"upload_date": match.group(1)}) if match else None


def write_index(output: Path, manifest: dict, summaries: Path, since=None) -> None:
    playlist = manifest.get("playlist", {})
    videos = manifest.get("videos", {})
    lines = [
        f"# Research index: {playlist.get('title') or playlist.get('url') or 'Channel'}",
        "",
        f"- Channel: {playlist.get('url', '')}",
        f"- Videos discovered: {playlist.get('video_count', len(videos))}",
        f"- Video records in manifest: {len(videos)}",
        "",
        "| # | Video | Transcript | Translation(s) | Summary | Status |",
        "|---:|---|---|---|---|---|",
    ]
    for video_id, video in sorted(videos.items(), key=lambda item: item[1].get("playlist_index", 0)):
        transcript = video_transcript_path(output, video)
        summary = summaries / f"{transcript.stem}.summary.md" if transcript else None
        title = (video.get("title") or video_id).replace("|", "\\|").replace("\n", " ")
        transcript_link = f"[transcript]({transcript.name})" if transcript else "—"
        translation_links = []
        for language, translation in video.get("translations", {}).items():
            relative_path = translation.get("path", "")
            translated_file = output / relative_path
            if translation.get("status") == "done" and translated_file.is_file():
                translation_links.append(f"[{language}]({relative_path.replace(os.sep, '/')})")
        translation_link = "<br>".join(translation_links) if translation_links else "—"
        summary_link = f"[{summary.name}](summaries/{summary.name})" if summary and summary.is_file() else "—"
        uploaded = transcript_upload_date(video, transcript) if transcript else None
        if since is not None and (uploaded is None or uploaded < since):
            summary_status = "outside since window" if uploaded is not None else "upload date unknown"
        else:
            summary_status = "summary ready" if summary and summary.is_file() else "summary pending"
        lines.append(
            f"| {video.get('playlist_index', '')} | [{title}]({video.get('url', '')}) | "
            f"{transcript_link} | {translation_link} | {summary_link} | "
            f"{video.get('status', 'unknown')}; {summary_status} |"
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
        status = "translation_failed" if name.startswith("translation:") else "summary_failed"
        failures.append(("", name, status, detail))
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
    launcher = os.environ.get("YT_RESEARCH_LAUNCHER")
    raw_args = normalize_long_options(sys.argv[1:])
    if not raw_args:
        print_command_usage(launcher)
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True, help="YouTube channel /videos URL or @handle")
    parser.add_argument("--output", type=Path, help="Output folder (default: transcripts/@<channel-handle>)")
    parser.add_argument("--langs", default="en,ko", help="Caption language priority")
    parser.add_argument("--limit", type=int, help="Process only the first N videos")
    parser.add_argument("--delay-min", type=float, default=0.5)
    parser.add_argument("--delay-max", type=float, default=2.0)
    parser.add_argument(
        "--translate-to",
        metavar="LANGUAGE",
        help="Translate each available transcript into LANGUAGE using Codex",
    )
    parser.add_argument(
        "--since",
        type=parse_since,
        metavar="DATE|DAYS",
        help="Include videos uploaded on/after YYYY-MM-DD or a day offset (-1=yesterday, 0=today)",
    )
    parser.add_argument("--force", action="store_true", help="Re-extract transcripts and regenerate summaries")
    args = parser.parse_args(raw_args)
    try:
        args.channel = normalize_channel(args.channel)
    except ValueError as exc:
        parser.error(str(exc))

    if args.translate_to and not translation_language_slug(args.translate_to):
        parser.error("--translate-to must contain a language name or code, for example cn or Spanish")

    root = Path(__file__).resolve().parent
    output = (args.output or (root / "transcripts" / channel_folder(args.channel))).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output}", flush=True)
    summaries = output / "summaries"

    print(f"[1/7] Discovering channel videos and extracting transcripts: {args.channel}", flush=True)
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
    if args.since is not None:
        command.extend(["--since", args.since.isoformat()])
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
    print(f"[2/7] Found {len(videos)} video records; selecting available transcripts.", flush=True)
    errors = pipeline_errors
    transcripts = []
    for video_id, video in sorted(videos.items(), key=lambda item: item[1].get("playlist_index", 0)):
        transcript = video_transcript_path(output, video)
        if transcript is None:
            continue
        if args.since is not None:
            uploaded = transcript_upload_date(video, transcript)
            if uploaded is None or uploaded < args.since:
                continue
        transcripts.append((video_id, video, transcript))

    if args.translate_to:
        language = args.translate_to.strip()
        language_slug = translation_language_slug(language)
        target_language = "Simplified Chinese" if language.casefold() == "cn" else language
        translations_dir = output / "translations"
        translations_dir.mkdir(parents=True, exist_ok=True)
        translation_progress = ProgressBar("Translating transcripts", len(transcripts))
        print(f"[3/7] Translating {len(transcripts)} transcript(s) to {language}.", flush=True)
        for number, (video_id, video, transcript) in enumerate(transcripts, 1):
            translation_progress.update(number - 1, f"working on: {video.get('title') or video_id}")
            translation = translations_dir / f"{transcript.stem}.{language_slug}.md"
            relative_translation = translation.relative_to(output).as_posix()
            translation_error = translations_dir / f"{transcript.stem}.{language_slug}.error.txt"
            translations = video.setdefault("translations", {})
            translation_record = translations.setdefault(language, {})

            if translation.is_file() and not args.force:
                translation_record.update({"path": relative_translation, "status": "done"})
                translation_error.unlink(missing_ok=True)
                translation_progress.update(number, f"already translated: {video.get('title') or video_id}")
                save_manifest(output / "manifest.json", manifest)
                continue

            translation.unlink(missing_ok=True)
            transcript_relative = transcript.relative_to(output).as_posix()
            prompt = f"""Read the complete Markdown transcript at `{transcript_relative}` and translate it into {target_language}.

Return only the translated Markdown, with no introduction, notes, or summary. Preserve the YAML front matter exactly. Translate all transcript prose and headings without omitting or condensing content. Keep timestamps, speaker labels, URLs, video IDs, numbers, Markdown links, and block order unchanged. Do not add facts or explanations.

Write the translation as the final response using the codex exec output option."""
            with Spinner(f"[3/7] Translating {number}/{len(transcripts)} to {language}: {video.get('title') or video_id}"):
                ok, error = run_codex(prompt, translation, output)
            if ok:
                translation_record.update({"path": relative_translation, "status": "done"})
                translation_error.unlink(missing_ok=True)
                translation_progress.update(number, f"done: {video.get('title') or video_id}")
            else:
                translation.unlink(missing_ok=True)
                translation_record.update({"path": relative_translation, "status": "failed", "error": error})
                translation_error.write_text(error + "\n", encoding="utf-8")
                errors.append((f"translation: {video.get('title') or video_id} ({language})", error))
                print(f"  translation failed: {error}", file=sys.stderr)
                translation_progress.update(number, f"failed: {video.get('title') or video_id}")
            save_manifest(output / "manifest.json", manifest)
        if not transcripts:
            translation_progress.update(0, "no transcripts available")
    else:
        print("[3/7] Translation disabled; use --translate-to LANGUAGE to create translated copies.", flush=True)

    candidates = []
    eligible_summaries = set()
    for video_id, video, transcript in transcripts:
        summary = summaries / f"{transcript.stem}.summary.md"
        if summary.is_file():
            eligible_summaries.add(summary.resolve())
        if args.force or not summary.is_file():
            candidates.append((video_id, video, transcript, summary))

    print(f"[4/7] {len(candidates)} transcript(s) need an independent summary.", flush=True)
    summary_progress = ProgressBar("Generating summaries", len(candidates))
    for number, (video_id, video, transcript, summary) in enumerate(candidates, 1):
        title = video.get("title") or video_id
        summary_progress.update(number - 1, f"working on: {title}")
        if args.force:
            summary.unlink(missing_ok=True)
        prompt = f"""Read the complete transcript file at `{transcript.name}` in the current directory and write an independent summary of this one video.

Video title: {video.get('title') or video_id}
Video URL: {video.get('url', '')}

Write a concise Markdown summary with: a one-paragraph overview; the main points in order; named people, organizations, places, dates, and figures; notable claims clearly attributed to the speaker; and unresolved or unclear points. Preserve the transcript's language. Separate what the speaker says from your interpretation. Do not use outside sources or invent details. Save the final response to the requested output file through the codex exec output option."""
        with Spinner(f"[5/7] Summarizing {number}/{len(candidates)}: {title}"):
            ok, error = run_codex(prompt, summary, output)
        error_file = summaries / f"{transcript.stem}.error.txt"
        if ok:
            eligible_summaries.add(summary.resolve())
            error_file.unlink(missing_ok=True)
            summary_progress.update(number, f"done: {title}")
        else:
            summary.unlink(missing_ok=True)
            errors.append((video.get("title") or video_id, error))
            summaries.mkdir(parents=True, exist_ok=True)
            error_file.write_text(error + "\n", encoding="utf-8")
            print(f"  summary failed: {error}", file=sys.stderr)
            summary_progress.update(number, f"failed: {title}")

    if not candidates:
        summary_progress.update(0, "nothing to summarize")

    ready = [
        p for p in summaries.glob("*.summary.md")
        if p.is_file() and (args.since is None or p.resolve() in eligible_summaries)
    ] if summaries.exists() else []
    report = output / "RESEARCH.md"
    if ready:
        print(f"[6/7] Updating cross-video research report from {len(ready)} summary file(s).", flush=True)
        summary_names = "\n".join(f"- summaries/{p.name}" for p in sorted(ready))
        prior_note = f"Read the current report at `{report.name}` and update it without losing prior findings. " if report.is_file() else "Create a new report. "
        prompt = f"""{prior_note}Read and synthesize every individual video summary listed below into a cross-video research report. The current directory contains these files:
{summary_names}

Identify recurring themes, actors, positions, supporting examples, changes over time when dates permit, and meaningful disagreements or gaps. Distinguish reported claims from established facts; this task does not include external fact-checking. Include a short executive overview, thematic sections, a dated timeline when supported, and source links to the individual summaries using their listed relative paths. Keep uncertainty explicit. Do not invent connections unsupported by the summaries."""
        with Spinner("[6/7] Updating cross-video research report"):
            ok, error = run_codex(prompt, report, output)
        if not ok:
            errors.append(("cross-video research report", error))
            (output / "RESEARCH.error.txt").write_text(error + "\n", encoding="utf-8")
            print(f"Research report update failed: {error}", file=sys.stderr)
        else:
            (output / "RESEARCH.error.txt").unlink(missing_ok=True)
    else:
        print("[6/7] No summaries are available; skipping cross-video report.", flush=True)

    print("[7/7] Writing index and failure list.", flush=True)
    write_index(output, manifest, summaries, args.since)
    write_failures(output, manifest, errors)
    print(f"Index:    {output / 'INDEX.md'}")
    print(f"Failures: {output / 'FAILURES.md'}")
    if report.is_file():
        print(f"Research: {report}")
    return 1 if errors else extracted.returncode


if __name__ == "__main__":
    sys.exit(main())
