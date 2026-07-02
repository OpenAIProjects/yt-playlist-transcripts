"""Allow `python -m yt_playlist_transcripts`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
