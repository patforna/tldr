# tldr

Summarise YouTube videos, articles, and PDFs from the command line via Claude.

## Usage

```
tldr <source> [--model MODEL] [--keep] [--force]
```

- **YouTube**: extracts transcript via `youtube-transcript-api` (falls back to `yt-dlp`)
- **Articles**: extracts main content via `trafilatura`
- **PDFs**: extracts text via `pymupdf` (supports URLs and local file paths)
- Pipes extracted text through `claude -p` for a concise summary with a "watch/read in full" verdict

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-m`, `--model` | `opus` | Claude model (`haiku`, `sonnet`, `opus`) |
| `-k`, `--keep` | | Save extracted full content to `tldr_content.txt` |
| `-f`, `--force` | | Bypass cache — re-download content and re-generate summary |

### Caching

tldr caches both extracted content and generated summaries so repeated lookups
are instant. Summaries are cached per model, so switching models (e.g. `--model sonnet`)
will generate and cache a fresh summary while reusing the cached content.

The cache directory follows platform conventions:

| Platform | Directory |
|----------|-----------|
| Linux | `$XDG_CACHE_HOME/tldr` (defaults to `~/.cache/tldr`) |
| macOS | `~/Library/Caches/tldr` |

Inside the cache directory, each source gets its own subdirectory named by a hash
of the URL (or file path + modification time for local files):

```
~/.cache/tldr/
└── 3a7b9c1e4f2d8a06/        # hash of the source URL
    ├── content.txt           # extracted text
    ├── opus.summary.txt      # summary generated with --model opus
    └── sonnet.summary.txt    # summary generated with --model sonnet
```

To clear the entire cache, delete the directory (e.g. `rm -rf ~/.cache/tldr`).

For local PDF files, the cache automatically invalidates when the file is modified.

Use `--force` to skip the cache entirely and re-download and re-summarise from
scratch. The fresh results are still written back to the cache.

## Examples

```bash
tldr "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
tldr "https://example.com/some-article"
tldr ~/Documents/report.pdf
tldr "https://example.com/paper.pdf"
tldr "https://example.com/deep-dive" -m sonnet
tldr "https://example.com/some-article" --force   # bypass cache
```

## Install

### Local

Requires [uv](https://docs.astral.sh/uv/) and [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

To run from anywhere, add a wrapper script somewhere on your `PATH`:

```bash
#!/usr/bin/env bash
PYTHONPATH=/path/to/tldr uv run --project /path/to/tldr python -m tldr "$@"
```

### Docker

```bash
docker compose run --rm tldr 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
```
To run from anywhere, add a wrapper script somewhere on your `PATH`:

```bash
#!/usr/bin/env bash
TLDR_OUTPUT="$PWD" docker compose -f /path/to/tldr/docker-compose.yml run --rm tldr "$@"
```

