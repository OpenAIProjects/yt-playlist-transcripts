"""Console entry point.

`yt-playlist-transcripts <url> [...]`         -> extract (default command)
`yt-playlist-transcripts extract <url> [...]` -> extract (explicit)
`yt-playlist-transcripts regen <dir> [...]`   -> rebuild .md from .raw.json
`yt-playlist-transcripts verify <dir> [...]`  -> coverage / structure checks
"""

import sys

from . import extract, regen, verify

COMMANDS = {
    "extract": extract.main,
    "regen": regen.main,
    "verify": verify.main,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in COMMANDS:
        return COMMANDS[argv[0]](argv[1:])
    # Default command is extract: `yt-playlist-transcripts <playlist_url>`.
    return extract.main(argv)


if __name__ == "__main__":
    sys.exit(main())
