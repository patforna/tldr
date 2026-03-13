"""tldr — Summarise YouTube videos, articles, and PDFs via CLI."""

import argparse
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from youtube_transcript_api import YouTubeTranscriptApi


def status(msg: str) -> None:
    print(f":: {msg}", file=sys.stderr, flush=True)


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


def fetch_youtube_transcript(url: str) -> str:
    """Fetch YouTube transcript, trying youtube-transcript-api first, then yt-dlp."""
    video_id = extract_video_id(url)
    if not video_id:
        print(f"error: could not extract video ID from {url}", file=sys.stderr)
        sys.exit(1)

    title, date = _fetch_youtube_meta(url)
    if title:
        status(f"{title} ({date})" if date else title)

    # Try youtube-transcript-api first
    status("fetching transcript...")
    try:
        ytt_api = YouTubeTranscriptApi()
        try:
            transcript = ytt_api.fetch(video_id, languages=["en"])
        except Exception:
            transcript = next(iter(ytt_api.list(video_id))).fetch()
        return " ".join(snippet.text for snippet in transcript.snippets)
    except Exception as e:
        status(f"transcript api failed ({e}), trying yt-dlp...")

    # Fallback: yt-dlp
    return _fetch_transcript_ytdlp(url)


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


def fetch_article_text(url: str) -> str:
    """Extract article text using trafilatura."""
    import trafilatura

    status("fetching article...")
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        print(f"error: could not fetch {url}", file=sys.stderr)
        sys.exit(1)

    title = _extract_html_title(downloaded)
    if title:
        date = _extract_html_date(downloaded)
        status(f"{title} ({date})" if date else title)

    status("extracting text...")
    text = trafilatura.extract(downloaded)
    if not text:
        print(f"error: could not extract text from {url}", file=sys.stderr)
        sys.exit(1)

    return text


def fetch_pdf_text(source: str) -> str:
    """Extract text from a local PDF file or a PDF URL."""
    import pymupdf

    # Resolve source to a file path
    if source.startswith(("http://", "https://")):
        status("downloading PDF...")
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "document.pdf"
            try:
                urllib.request.urlretrieve(source, pdf_path)
            except Exception as e:
                print(f"error: could not download PDF: {e}", file=sys.stderr)
                sys.exit(1)
            return _extract_pdf(pymupdf, pdf_path)
    else:
        path = Path(source).expanduser()
        if not path.is_file():
            print(f"error: file not found: {source}", file=sys.stderr)
            sys.exit(1)
        return _extract_pdf(pymupdf, path)


def _extract_pdf(pymupdf, path: Path) -> str:
    """Open a PDF and extract text with metadata display and truncation."""
    MAX_CHARS = 500_000

    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        print(f"error: could not open PDF: {e}", file=sys.stderr)
        sys.exit(1)

    if doc.is_encrypted:
        print("error: PDF is encrypted/password-protected", file=sys.stderr)
        sys.exit(1)

    # Display metadata
    title = doc.metadata.get("title") or None
    date = None
    raw_date = doc.metadata.get("creationDate") or ""
    if m := re.match(r"D:(\d{4})(\d{2})(\d{2})", raw_date):
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    if title:
        status(f"{title} ({date})" if date else title)
    status(f"{len(doc)} pages")

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

    return text


def summarise(text: str, model: str) -> None:
    """Pipe text through claude CLI for summarisation."""
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
        ["claude", "-p", "--model", model, prompt],
        text=True,
    )
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        prog="tldr",
        description="Summarise YouTube videos, articles, and PDFs via Claude.",
    )
    parser.add_argument("source", help="YouTube URL, article URL, PDF URL, or local PDF path")
    parser.add_argument("-m", "--model", default="opus", help="claude model to use (default: opus)")
    parser.add_argument("-k", "--keep", action="store_true", help="save extracted full content to a file")
    args = parser.parse_args()
    source = args.source
    if source.startswith(("http://", "https://")):
        source = re.sub(r'\\([?=&])', r'\1', source)  # strip shell escapes

    if is_pdf(source):
        text = fetch_pdf_text(source)
    elif is_youtube(source):
        text = fetch_youtube_transcript(source)
    else:
        text = fetch_article_text(source)

    if args.keep:
        Path("tldr_content.txt").write_text(text)
        status("saved to tldr_content.txt")

    summarise(text, args.model)


if __name__ == "__main__":
    main()
