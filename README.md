# tldr

Summarise YouTube videos and articles from the command line via Claude.

## Usage

```
tldr <url> [-m MODEL]
```

- **YouTube**: extracts transcript via `youtube-transcript-api` (falls back to `yt-dlp`)
- **Articles**: extracts main content via `trafilatura`
- Pipes extracted text through `claude -p` for a concise summary with a "watch/read in full" verdict

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-m`, `--model` | `opus` | Claude model (`haiku`, `sonnet`, `opus`) |

## Examples

```bash
tldr "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
tldr "https://example.com/some-article"
tldr "https://example.com/deep-dive" -m sonnet
```

## Install

### Local

Requires [uv](https://docs.astral.sh/uv/) and [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

To run from anywhere, add a wrapper script somewhere on your `PATH`:

```bash
#!/usr/bin/env bash
cd /path/to/tldr && uv run python -m tldr "$@"
```

### Docker

```bash
docker compose run --rm tldr 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
```
To run from anywhere, add a wrapper script somewhere on your `PATH`:

```bash
#!/usr/bin/env bash
docker compose -f /path/to/tldr/docker-compose.yml run --rm tldr "$@"
```

