# tldr

Summarise YouTube videos, articles, and PDFs from the command line via Claude.

## Usage

```
tldr <source> [--critique] [--model MODEL] [--force] [--keep]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-c`, `--critique` | | Research and critique the content instead of summarising |
| `-m`, `--model` | `opus` | Claude model (`haiku`, `sonnet`, `opus`) |
| `-f`, `--force` | | Bypass cache — re-download content and regenerate output |
| `-k`, `--keep` | | Save extracted content to `tldr_content.txt` |

### Examples

```bash
tldr "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
tldr "https://example.com/some-article"
tldr ~/Documents/report.pdf
tldr "https://example.com/paper.pdf"
tldr "https://example.com/deep-dive" --model sonnet
tldr "https://example.com/some-article" --force   # bypass cache
tldr "https://example.com/some-article" -c       # critique instead of summarise
```

Pipe through [Glow](https://github.com/charmbracelet/glow) for prettier terminal rendering:

```bash
tldr "https://example.com/some-article" | glow
```

## How it works

- **YouTube**: extracts transcript via `youtube-transcript-api` (falls back to `yt-dlp`)
- **Articles**: extracts main content via `trafilatura`
- **PDFs**: extracts text via `pymupdf` (supports URLs and local file paths)
- Pipes extracted text through `claude -p` for a concise summary with a **"watch/read in full" verdict**

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

Use `--force` to skip the cache entirely and re-download content from scratch.
The fresh content is still written back to the cache. In summary mode, a new
summary is also regenerated and cached.

### Critique mode

The `--critique` flag switches from summarisation to critical analysis. It runs a
3-phase pipeline:

1. **Assess complexity** — rates the content 1–10 for complexity/contestability
2. **Research in parallel** — spawns a proportional team of subagents, each
   researching one specific angle (validating claims, finding counterarguments,
   checking for missing context)
3. **Synthesise** — combines all research into a concise critique with bullet-point
   findings and a one-line overall assessment

The number of research subagents scales with assessed complexity:

| Complexity | Subagents | Use case |
|------------|-----------|----------|
| 1–2 | 0 | Trivial / uncontested content — no research needed |
| 3–5 | 2–3 | Moderate claims needing basic validation |
| 6–8 | 4–7 | Complex or contested topics requiring multiple angles |
| 9–10 | 8–10 | Highly complex content needing thorough investigation |

The prompt instructs Claude not to manufacture nitpicks — if the content is accurate
and uncontested, the critique will say so plainly.

Typical workflow — summarise first, then critique if sceptical:

```bash
tldr "https://example.com/bold-claims"           # quick summary
tldr "https://example.com/bold-claims" -c        # in-depth critique (reuses cached content)
tldr "https://example.com/bold-claims" -c -f     # re-download and critique from scratch
```

Critique mode reuses the cached content (so there's no re-download), but it works
from the raw source text — not the summary. This avoids anchoring the critique to
whatever the summary chose to highlight or omit.

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
