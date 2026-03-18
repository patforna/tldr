"""tldr — Summarise YouTube videos, articles, and PDFs via CLI."""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

from youtube_transcript_api import YouTubeTranscriptApi

from tldr import cache


def status(msg: str) -> None:
    print(f":: {msg}", file=sys.stderr, flush=True)


def _truncate(text: str, max_len: int = 60) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "\u2026"


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        if m := re.search(pattern, url):
            return m.group(1)
    return None


def is_youtube(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url))


def is_pdf(source: str) -> bool:
    """Check if source is a local PDF file or a URL pointing to a PDF."""
    if Path(source).suffix.lower() == ".pdf":
        return True
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and parsed.path.lower().endswith(".pdf")


def _fetch_youtube_meta(url: str) -> tuple[str | None, str | None]:
    """Fetch YouTube video title and upload date via yt-dlp."""
    result = subprocess.run(
        ["yt-dlp", "--print", "%(title)s", "--print", "%(upload_date>%Y-%m-%d)s",
         "--no-download", url],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        lines = result.stdout.strip().splitlines()
        title = lines[0] if lines else None
        date = lines[1] if len(lines) > 1 and lines[1] != "NA" else None
        return title, date
    return None, None


def _extract_html_title(html: str) -> str | None:
    """Extract <title> from HTML."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None


def _extract_html_date(html: str) -> str | None:
    """Extract publish date from HTML via htmldate."""
    try:
        from htmldate import find_date
        return find_date(html)
    except Exception:
        return None


def fetch_youtube_transcript(url: str) -> tuple[str, str | None]:
    """Fetch YouTube transcript, trying youtube-transcript-api first, then yt-dlp.

    Returns (text, title_line).
    """
    video_id = extract_video_id(url)
    if not video_id:
        print(f"error: could not extract video ID from {url}", file=sys.stderr)
        sys.exit(1)

    title, date = _fetch_youtube_meta(url)
    title_line = None
    if title:
        title_line = f"{title} ({date})" if date else title

    # Try youtube-transcript-api first
    if title_line:
        status(f"fetching: {_truncate(title_line)}")
    else:
        status("fetching transcript...")
    try:
        ytt_api = YouTubeTranscriptApi()
        try:
            transcript = ytt_api.fetch(video_id, languages=["en"])
        except Exception:
            transcript = next(iter(ytt_api.list(video_id))).fetch()
        return " ".join(snippet.text for snippet in transcript.snippets), title_line
    except Exception as e:
        status(f"transcript api failed ({e}), trying yt-dlp...")

    # Fallback: yt-dlp
    return _fetch_transcript_ytdlp(url), title_line


def _fetch_transcript_ytdlp(url: str) -> str:
    """Fetch transcript using yt-dlp as fallback."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_template = str(Path(tmpdir) / "sub")
        cmd = [
            "yt-dlp",
            "--write-subs",
            "--write-auto-sub",
            "--sub-lang", "en",
            "--sub-format", "vtt",
            "--skip-download",
            "-o", out_template,
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"error: yt-dlp failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)

        # Find the subtitle file, prefer English
        sub_files = list(Path(tmpdir).glob("*.vtt"))
        if not sub_files:
            print("error: no subtitle file produced by yt-dlp", file=sys.stderr)
            sys.exit(1)

        en_files = [f for f in sub_files if ".en" in f.name]
        return _parse_vtt((en_files[0] if en_files else sub_files[0]).read_text())


def _parse_vtt(vtt_content: str) -> str:
    """Extract plain text from VTT subtitle content."""
    lines = []
    for line in vtt_content.splitlines():
        # Skip headers, timestamps, and blank lines
        if not line.strip():
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if re.match(r"\d{2}:\d{2}", line):
            continue
        # Strip VTT tags like <c> </c>
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean and (not lines or clean != lines[-1]):
            lines.append(clean)
    return " ".join(lines)


def fetch_article_text(url: str) -> tuple[str, str | None]:
    """Extract article text using trafilatura.

    Returns (text, title_line).
    """
    import trafilatura

    status("fetching article...")
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        print(f"error: could not fetch {url}", file=sys.stderr)
        sys.exit(1)

    title_line = None
    title = _extract_html_title(downloaded)
    if title:
        date = _extract_html_date(downloaded)
        title_line = f"{title} ({date})" if date else title
        status(f"fetching: {_truncate(title_line)}")

    status("extracting text...")
    text = trafilatura.extract(downloaded)
    if not text:
        print(f"error: could not extract text from {url}", file=sys.stderr)
        sys.exit(1)

    return text, title_line


def fetch_pdf_text(source: str) -> tuple[str, str | None]:
    """Extract text from a local PDF file or a PDF URL.

    Returns (text, title_line).
    """
    import pymupdf

    # Resolve source to a file path
    if source.startswith(("http://", "https://")):
        status("fetching...")
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "document.pdf"
            try:
                urllib.request.urlretrieve(source, pdf_path)
            except Exception as e:
                print(f"error: could not download PDF: {e}", file=sys.stderr)
                sys.exit(1)
            text, title_line = _extract_pdf(pymupdf, pdf_path)
    else:
        path = Path(source).expanduser()
        if not path.is_file():
            print(f"error: file not found: {source}", file=sys.stderr)
            sys.exit(1)
        text, title_line = _extract_pdf(pymupdf, path)

    if title_line:
        status(f"fetching: {_truncate(title_line)}")
    elif not source.startswith(("http://", "https://")):
        status("fetching...")
    return text, title_line


def _extract_pdf(pymupdf, path: Path) -> tuple[str, str | None]:
    """Open a PDF and extract text with truncation.

    Returns (text, title_line) where title_line may be None.
    """
    MAX_CHARS = 500_000

    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        print(f"error: could not open PDF: {e}", file=sys.stderr)
        sys.exit(1)

    if doc.is_encrypted:
        print("error: PDF is encrypted/password-protected", file=sys.stderr)
        sys.exit(1)

    title = doc.metadata.get("title") or None
    title_line = None
    date = None
    raw_date = doc.metadata.get("creationDate") or ""
    if m := re.match(r"D:(\d{4})(\d{2})(\d{2})", raw_date):
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    if title:
        title_line = f"{title} ({date})" if date else title

    status("extracting text...")
    texts = []
    char_count = 0
    for i, page in enumerate(doc):
        page_text = page.get_text()
        if char_count + len(page_text) > MAX_CHARS:
            texts.append(f"\n\n[Truncated: first {i} of {len(doc)} pages]")
            break
        texts.append(page_text)
        char_count += len(page_text)
    doc.close()

    text = "\n".join(texts)
    if not text.strip():
        print("error: no extractable text in PDF (may be scanned/image-only)", file=sys.stderr)
        sys.exit(1)

    return text, title_line


CLAUDE_TIMEOUT = 300


def _run_claude(prompt: str, model: str) -> str:
    """Run claude CLI and return its stdout."""
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(f"error: claude timed out after {CLAUDE_TIMEOUT}s", file=sys.stderr)
        sys.exit(1)
    if result.returncode != 0:
        print(f"error: claude failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def critique(text: str, model: str) -> None:
    """Research and critique the content's claims and arguments."""
    # Phase 1: Assess complexity (cheap model)
    status("assessing complexity...")
    assessment = _run_claude(
        "Analyze the following content and respond with ONLY valid JSON (no markdown fences).\n"
        "Return an object with:\n"
        '- "complexity": integer 1-10 rating of how complex, nuanced, or contestable the topic is\n'
        '- "tasks": a list of specific research tasks to validate or critique the content.\n'
        "  Each task is a short string describing one angle to research.\n"
        "  Scale the number of tasks to the complexity:\n"
        "    complexity 1-2: empty list (content is trivial/uncontested)\n"
        "    complexity 3-4: 1-2 tasks\n"
        "    complexity 5-6: 3-4 tasks\n"
        "    complexity 7-8: 5-7 tasks\n"
        "    complexity 9-10: 8-10 tasks\n\n"
        "Content:\n" + text,
        "haiku",
    )

    try:
        parsed = json.loads(assessment)
        complexity = parsed["complexity"]
        tasks = parsed["tasks"]
    except (json.JSONDecodeError, KeyError):
        status("warning: could not parse complexity assessment, proceeding without research")
        complexity = 0
        tasks = []

    tasks = tasks[:10]  # hard cap regardless of model output
    status(f"complexity {complexity}/10, {len(tasks)} research {'task' if len(tasks) == 1 else 'tasks'}")

    # Phase 2: Research tasks in parallel (each is an independent claude call)
    findings = {}
    if tasks:
        status("researching...")

        def research(task: str) -> tuple[str, str]:
            result = _run_claude(
                "You are a research analyst. Critically evaluate one specific aspect "
                "of a piece of content. Provide evidence, counterarguments, alternative "
                "perspectives, and an assessment of accuracy.\n\n"
                f"Research task: {task}\n\n"
                "Original content for context:\n" + text,
                model,
            )
            return task, result

        with ThreadPoolExecutor(max_workers=min(len(tasks), 10)) as pool:
            futures = [pool.submit(research, t) for t in tasks]
            for i, future in enumerate(as_completed(futures), 1):
                task, result = future.result()
                findings[task] = result
                status(f"research {i}/{len(tasks)} done")

    # Phase 3: Synthesise critique
    status("synthesising critique...")
    research_block = ""
    if findings:
        sections = []
        for task, result in findings.items():
            sections.append(f"### {task}\n{result}")
        research_block = "\n\n---\n\n".join(sections)

    synthesis_prompt = (
        "You are a critical analyst. Based on the original content and research findings below, "
        "write a short, focused critique summary.\n\n"
        "Guidelines:\n"
        "- Use bullet points for individual findings\n"
        "- Validate or challenge key claims based on the research\n"
        "- Note any important alternative perspectives or missing context\n"
        "- If the content is largely accurate and uncontested, say so plainly — "
        "do NOT force criticism or manufacture nitpicks\n"
        "- End with a one-line overall assessment\n\n"
        "ORIGINAL CONTENT:\n" + text + "\n\n"
    )
    if research_block:
        synthesis_prompt += "RESEARCH FINDINGS:\n" + research_block + "\n"

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model],
            input=synthesis_prompt,
            text=True,
            timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(f"\nerror: claude timed out after {CLAUDE_TIMEOUT}s", file=sys.stderr)
        sys.exit(1)
    sys.exit(result.returncode)


def summarise(text: str, model: str) -> str:
    """Pipe text through claude CLI for summarisation and return the summary."""
    status("summarising...")
    prompt = (
        "Summarise the following content concisely. "
        "Use bullet points for key takeaways. "
        "Keep it short — aim for a quick overview someone can scan in 30 seconds.\n\n"
        "After the summary, evaluate whether the full piece genuinely warrants the time investment. "
        "The bar is high — most content is adequately captured by a summary. "
        "Only recommend the full piece if it has exceptional qualities the summary can't convey: "
        "nuanced arguments, compelling storytelling, rich demonstrations, or depth that loses its value when compressed. "
        "Short or straightforward content never qualifies. "
        "If and ONLY if the full piece clears that bar, add a blank line and then: "
        "WATCH/READ IN FULL — one sentence explaining what makes it worth the time. "
        "If the summary is sufficient (the common case), do not add this line at all.\n\n"
        + text
    )
    result = subprocess.run(
        ["claude", "-p", "--model", model],
        input=prompt,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(
        prog="tldr",
        description="Summarise YouTube videos, articles, and PDFs via Claude.",
    )
    parser.add_argument("source", help="YouTube URL, article URL, PDF URL, or local PDF path")
    parser.add_argument("-m", "--model", default="opus", help="claude model to use (default: opus)")
    parser.add_argument("-k", "--keep", action="store_true", help="save extracted full content to a file")
    parser.add_argument("-f", "--force", action="store_true", help="bypass cache and re-download/re-summarise (results are still cached)")
    parser.add_argument("-c", "--critique", action="store_true", help="research and critique the content's claims")
    args = parser.parse_args()
    source = args.source
    if source.startswith(("http://", "https://")):
        source = re.sub(r'\\([?=&])', r'\1', source)  # strip shell escapes

    use_cache = not args.force

    # Check for cached summary first (fastest path) — only for summarise mode
    if use_cache and not args.critique:
        cached_summary = cache.get_summary(source, args.model)
        if cached_summary is not None:
            status("using cached summary")
            print(cached_summary, end="")
            if args.keep:
                cached_content = cache.get_content(source)
                if cached_content is not None:
                    Path("tldr_content.txt").write_text(cached_content)
                    status("saved to tldr_content.txt")
                else:
                    status("cached content unavailable, use -f to re-download")
            return

    # Check for cached content (avoids re-downloading)
    text = None
    title_line = None
    if use_cache:
        text = cache.get_content(source)
        if text is not None:
            status("using cached content, re-summarising...")

    # Fetch content if not cached
    if text is None:
        if is_pdf(source):
            text, title_line = fetch_pdf_text(source)
        elif is_youtube(source):
            text, title_line = fetch_youtube_transcript(source)
        else:
            text, title_line = fetch_article_text(source)
        cache.put_content(source, text)

    if args.keep:
        Path("tldr_content.txt").write_text(text)
        status("saved to tldr_content.txt")

    if args.critique:
        critique(text, args.model)
    else:
        summary = summarise(text, args.model)
        if title_line:
            summary = f"# {title_line}\n\n{summary}"
        cache.put_summary(source, args.model, summary)
        print(summary, end="")


if __name__ == "__main__":
    main()
