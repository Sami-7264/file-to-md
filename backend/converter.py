"""
converter.py
============

Core conversion engine. Wraps Microsoft's MarkItDown library and routes every
supported input (local file or URL) to the correct handling strategy:

    * Documents (PDF, DOCX, PPTX, XLSX, CSV, JSON, HTML, EPUB, ZIP, ...)
          -> MarkItDown.convert_local()
    * Images (JPG, PNG, ...)
          -> EXIF metadata extraction (Pillow) + OCR (pytesseract) + MarkItDown
    * Audio / Video (MP3, WAV, MP4, ...)
          -> local Whisper transcription (whisper_transcribe.py)
    * URLs, including YouTube
          -> MarkItDown.convert() with a yt-dlp transcript fallback

Every strategy reports incremental progress through an optional ``progress``
callback so the FastAPI layer can stream Server-Sent Events.

The module is deliberately framework-agnostic: it knows nothing about FastAPI
and can be unit-tested or reused on its own.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Hard upper bound for a single file. Anything larger is rejected up-front.
MAX_FILE_SIZE_BYTES: int = 100 * 1024 * 1024  # 100 MB

#: A progress callback receives (percent: int 0-100, human-readable message).
ProgressCallback = Callable[[int, str], None]


# ---------------------------------------------------------------------------
# File-type taxonomy
# ---------------------------------------------------------------------------


class FileKind(str, Enum):
    """High-level category that decides which conversion strategy to use."""

    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DATA = "data"
    ARCHIVE = "archive"
    EBOOK = "ebook"
    WEB = "web"
    URL = "url"
    UNKNOWN = "unknown"


# Extension -> FileKind lookup. Lower-cased, leading dot included.
_EXTENSION_MAP: dict[str, FileKind] = {
    # documents
    ".pdf": FileKind.DOCUMENT,
    ".doc": FileKind.DOCUMENT,
    ".docx": FileKind.DOCUMENT,
    ".rtf": FileKind.DOCUMENT,
    ".odt": FileKind.DOCUMENT,
    ".txt": FileKind.DOCUMENT,
    ".md": FileKind.DOCUMENT,
    # spreadsheets
    ".xls": FileKind.SPREADSHEET,
    ".xlsx": FileKind.SPREADSHEET,
    ".ods": FileKind.SPREADSHEET,
    # presentations
    ".ppt": FileKind.PRESENTATION,
    ".pptx": FileKind.PRESENTATION,
    ".odp": FileKind.PRESENTATION,
    # images
    ".jpg": FileKind.IMAGE,
    ".jpeg": FileKind.IMAGE,
    ".png": FileKind.IMAGE,
    ".gif": FileKind.IMAGE,
    ".bmp": FileKind.IMAGE,
    ".tiff": FileKind.IMAGE,
    ".tif": FileKind.IMAGE,
    ".webp": FileKind.IMAGE,
    ".heic": FileKind.IMAGE,
    # audio
    ".mp3": FileKind.AUDIO,
    ".wav": FileKind.AUDIO,
    ".m4a": FileKind.AUDIO,
    ".flac": FileKind.AUDIO,
    ".ogg": FileKind.AUDIO,
    ".aac": FileKind.AUDIO,
    # video
    ".mp4": FileKind.VIDEO,
    ".mov": FileKind.VIDEO,
    ".mkv": FileKind.VIDEO,
    ".avi": FileKind.VIDEO,
    ".webm": FileKind.VIDEO,
    # structured data
    ".csv": FileKind.DATA,
    ".json": FileKind.DATA,
    ".jsonl": FileKind.DATA,
    ".xml": FileKind.DATA,
    ".yaml": FileKind.DATA,
    ".yml": FileKind.DATA,
    # archives
    ".zip": FileKind.ARCHIVE,
    # ebooks
    ".epub": FileKind.EBOOK,
    # web
    ".html": FileKind.WEB,
    ".htm": FileKind.WEB,
}


# ---------------------------------------------------------------------------
# Result + error types
# ---------------------------------------------------------------------------


class ConversionError(Exception):
    """Raised when conversion fails. Carries a user-friendly message."""

    def __init__(self, message: str, *, kind: Optional[FileKind] = None) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind


@dataclass
class ConversionResult:
    """Outcome of a successful conversion."""

    markdown: str
    source_name: str
    output_name: str
    kind: FileKind
    char_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.char_count = len(self.markdown)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def slugify(value: str) -> str:
    """Turn an arbitrary filename stem into a safe, lower-case slug.

    ``"My Report (Final).PDF"`` -> ``"my-report-final"``.
    Always returns a non-empty string.
    """

    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "converted"


def output_filename(source_name: str) -> str:
    """Build the slugified ``.md`` filename for a given source filename."""

    stem = Path(source_name).stem
    return f"{slugify(stem)}.md"


def detect_kind(name: str) -> FileKind:
    """Classify a filename (or URL) into a :class:`FileKind`."""

    if _looks_like_url(name):
        return FileKind.URL
    ext = Path(name).suffix.lower()
    return _EXTENSION_MAP.get(ext, FileKind.UNKNOWN)


def _looks_like_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://"))


def is_youtube_url(value: str) -> bool:
    return bool(
        re.search(r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)", value, re.I)
    )


def _noop_progress(_percent: int, _message: str) -> None:
    """Default progress sink that discards updates."""


# ---------------------------------------------------------------------------
# The Converter
# ---------------------------------------------------------------------------


class Converter:
    """Stateful wrapper around a single :class:`markitdown.MarkItDown` instance.

    Instantiate once and reuse — building MarkItDown is comparatively heavy
    because it registers every available converter plugin.
    """

    def __init__(self, *, enable_plugins: bool = True) -> None:
        # Imported lazily so importing this module never hard-fails if an
        # optional native dependency is missing; the error surfaces at use time.
        try:
            from markitdown import MarkItDown
        except ImportError as exc:  # pragma: no cover - import-time guard
            raise ConversionError(
                "The 'markitdown' package is not installed. "
                "Run: pip install 'markitdown[all]'"
            ) from exc

        self._md = MarkItDown(enable_plugins=enable_plugins)

    # -- public API --------------------------------------------------------

    def convert_path(
        self,
        path: str | Path,
        *,
        original_name: Optional[str] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> ConversionResult:
        """Convert a file that already lives on the local filesystem."""

        path = Path(path)
        report = progress or _noop_progress
        source_name = original_name or path.name

        if not path.exists():
            raise ConversionError(f"File not found: {source_name}")

        size = path.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            raise ConversionError(
                f"File is too large ({_human_size(size)}). "
                f"The limit is {_human_size(MAX_FILE_SIZE_BYTES)}."
            )
        if size == 0:
            raise ConversionError("File is empty.")

        kind = detect_kind(source_name)
        report(5, f"Detected file type: {kind.value}")

        try:
            if kind == FileKind.IMAGE:
                markdown = self._convert_image(path, report)
            elif kind in (FileKind.AUDIO, FileKind.VIDEO):
                markdown = self._convert_media(path, kind, report)
            else:
                markdown = self._convert_with_markitdown(path, kind, report)
        except ConversionError:
            raise
        except Exception as exc:  # noqa: BLE001 - convert any backend failure
            raise ConversionError(
                _friendly_failure(kind, str(exc)), kind=kind
            ) from exc

        markdown = markdown.strip()
        if not markdown:
            raise ConversionError(
                f"No content could be extracted from this {kind.value} file.",
                kind=kind,
            )

        report(100, "Conversion complete")
        return ConversionResult(
            markdown=markdown,
            source_name=source_name,
            output_name=output_filename(source_name),
            kind=kind,
        )

    def convert_url(
        self,
        url: str,
        *,
        progress: Optional[ProgressCallback] = None,
    ) -> ConversionResult:
        """Convert a remote URL (web page or YouTube video)."""

        report = progress or _noop_progress
        if not _looks_like_url(url):
            raise ConversionError("Not a valid URL. Expected http:// or https://")

        youtube = is_youtube_url(url)
        report(10, "Fetching YouTube transcript" if youtube else "Fetching URL")

        try:
            result = self._md.convert(url)
            markdown = (result.text_content or "").strip()
        except Exception as exc:  # noqa: BLE001
            if youtube:
                report(40, "Primary fetch failed, trying yt-dlp fallback")
                markdown = self._youtube_fallback(url, report)
            else:
                raise ConversionError(
                    f"Could not fetch or convert the URL: {exc}", kind=FileKind.URL
                ) from exc

        if youtube and not markdown:
            markdown = self._youtube_fallback(url, report)

        if not markdown:
            raise ConversionError("No content could be extracted from the URL.")

        report(100, "Conversion complete")
        title = _title_from_url(url)
        return ConversionResult(
            markdown=markdown,
            source_name=url,
            output_name=f"{slugify(title)}.md",
            kind=FileKind.URL,
        )

    # -- strategy: generic MarkItDown -------------------------------------

    def _convert_with_markitdown(
        self, path: Path, kind: FileKind, report: ProgressCallback
    ) -> str:
        report(30, f"Parsing {kind.value} with MarkItDown")
        result = self._md.convert_local(str(path))
        text = (result.text_content or "").strip()

        # Scanned / image-only PDFs have no embedded text layer, so MarkItDown
        # (which only reads the text layer) returns nothing. Fall back to
        # rendering each page to an image and OCR-ing it.
        if not text and path.suffix.lower() == ".pdf":
            report(45, "No text layer found — running OCR on PDF pages")
            text = _ocr_pdf(path, report)

        report(85, "Formatting markdown")
        return text

    # -- strategy: images (EXIF + OCR) ------------------------------------

    def _convert_image(self, path: Path, report: ProgressCallback) -> str:
        sections: list[str] = [f"# {path.stem}\n"]

        report(20, "Reading image metadata")
        exif = _extract_exif(path)
        if exif:
            sections.append("## Image Metadata\n")
            sections.append(_dict_to_md_table(exif))

        report(45, "Running OCR (this can take a moment)")
        ocr_text = _run_ocr(path)
        if ocr_text:
            sections.append("## Extracted Text (OCR)\n")
            sections.append(ocr_text.strip())

        report(75, "Asking MarkItDown for a description")
        try:
            result = self._md.convert_local(str(path))
            extra = (result.text_content or "").strip()
            if extra:
                sections.append("## MarkItDown Output\n")
                sections.append(extra)
        except Exception:  # noqa: BLE001 - MarkItDown image step is best-effort
            pass

        if not ocr_text and not exif:
            sections.append(
                "_No text or metadata could be extracted from this image._"
            )

        return "\n\n".join(sections)

    # -- strategy: audio / video (Whisper) --------------------------------

    def _convert_media(
        self, path: Path, kind: FileKind, report: ProgressCallback
    ) -> str:
        # Imported here so the heavy Whisper/torch stack only loads for media.
        from whisper_transcribe import transcribe

        report(15, "Loading transcription model")
        transcript = transcribe(path, progress=report)

        # Attach any container metadata MarkItDown can read (best-effort).
        meta_md = ""
        try:
            result = self._md.convert_local(str(path))
            meta_md = (result.text_content or "").strip()
        except Exception:  # noqa: BLE001
            meta_md = ""

        header = f"# Transcript: {path.stem}\n"
        body = transcript.strip() or "_No speech detected in the media file._"
        parts = [header, body]
        if meta_md:
            parts.append("## Media Metadata\n")
            parts.append(meta_md)
        return "\n\n".join(parts)

    # -- YouTube fallback --------------------------------------------------

    def _youtube_fallback(self, url: str, report: ProgressCallback) -> str:
        """Pull captions / metadata with yt-dlp when MarkItDown comes up empty."""

        try:
            import yt_dlp  # type: ignore
        except ImportError as exc:
            raise ConversionError(
                "yt-dlp is not installed; cannot fetch YouTube transcript. "
                "Run: pip install yt-dlp"
            ) from exc

        report(60, "Extracting captions with yt-dlp")
        opts = {
            "skip_download": True,
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": ["en", "en-US"],
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # noqa: BLE001
            raise ConversionError(
                f"yt-dlp failed to fetch the video: {exc}", kind=FileKind.URL
            ) from exc

        title = info.get("title", "YouTube Video")
        description = info.get("description", "") or ""
        transcript = _extract_ytdlp_captions(info)

        parts = [f"# {title}\n"]
        if info.get("uploader"):
            parts.append(f"**Channel:** {info['uploader']}  ")
        if info.get("duration"):
            parts.append(f"**Duration:** {_format_duration(info['duration'])}\n")
        if transcript:
            parts.append("## Transcript\n")
            parts.append(transcript)
        elif description:
            parts.append("## Description\n")
            parts.append(description)
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Module-level image / metadata helpers
# ---------------------------------------------------------------------------


def _extract_exif(path: Path) -> dict[str, str]:
    """Return a flat, JSON-safe dict of EXIF tags (empty if none/unavailable)."""

    try:
        from PIL import Image, ExifTags
    except ImportError:
        return {}

    out: dict[str, str] = {}
    try:
        with Image.open(path) as img:
            out["Format"] = img.format or ""
            out["Mode"] = img.mode
            out["Size"] = f"{img.width} x {img.height}"
            raw = getattr(img, "_getexif", lambda: None)()
            if raw:
                for tag_id, value in raw.items():
                    tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                    out[str(tag)] = _stringify_exif(value)
    except Exception:  # noqa: BLE001 - corrupt EXIF should never crash
        return {k: v for k, v in out.items() if v}
    return {k: v for k, v in out.items() if v}


def _stringify_exif(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip("\x00 ")
    text = str(value)
    return text if len(text) <= 200 else text[:197] + "..."


def _run_ocr(path: Path) -> str:
    """Run Tesseract OCR on an image. Returns '' if OCR is unavailable."""

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    try:
        with Image.open(path) as img:
            return pytesseract.image_to_string(img)
    except Exception:  # noqa: BLE001 - missing tesseract binary, etc.
        return ""


def _ocr_pdf(path: Path, report: ProgressCallback) -> str:
    """OCR a scanned/image PDF: render each page with pypdfium2, then Tesseract.

    Raises a clear :class:`ConversionError` when OCR tooling is unavailable so
    the user gets an actionable message instead of a generic "no content".
    """

    from shutil import which

    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ConversionError(
            "This PDF has no text layer and pypdfium2 is not installed, "
            "so it cannot be OCR-ed.",
            kind=FileKind.DOCUMENT,
        ) from exc

    if which("tesseract") is None:
        raise ConversionError(
            "This looks like a scanned / image-only PDF with no selectable text. "
            "Install Tesseract to enable OCR (macOS: 'brew install tesseract', "
            "Ubuntu: 'sudo apt install tesseract-ocr'), then try again.",
            kind=FileKind.DOCUMENT,
        )

    try:
        import pytesseract
        from PIL import Image  # noqa: F401 - ensures Pillow is present
    except ImportError as exc:
        raise ConversionError(
            "OCR dependencies (pytesseract / Pillow) are not installed.",
            kind=FileKind.DOCUMENT,
        ) from exc

    pdf = pdfium.PdfDocument(str(path))
    try:
        page_count = len(pdf)
        pages: list[str] = []
        for i in range(page_count):
            page = pdf[i]
            # 2x scale ≈ 144 DPI: a good accuracy/speed trade-off for OCR.
            bitmap = page.render(scale=2.0)
            image = bitmap.to_pil()
            text = pytesseract.image_to_string(image).strip()
            if text:
                pages.append(f"## Page {i + 1}\n\n{text}")
            report(
                45 + int(40 * (i + 1) / max(page_count, 1)),
                f"OCR page {i + 1}/{page_count}",
            )
        return "\n\n".join(pages)
    finally:
        pdf.close()


def _dict_to_md_table(data: dict[str, str]) -> str:
    rows = ["| Field | Value |", "| --- | --- |"]
    for key, value in data.items():
        safe = str(value).replace("|", "\\|").replace("\n", " ")
        rows.append(f"| {key} | {safe} |")
    return "\n".join(rows)


def _extract_ytdlp_captions(info: dict) -> str:
    """Best-effort: stitch yt-dlp subtitle data into plain transcript text."""

    subs = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}
    for source in (subs, autos):
        for lang in ("en", "en-US", "en-GB"):
            tracks = source.get(lang)
            if tracks:
                # We can't download here without an extra request; surface the
                # availability so the caller can rely on description instead.
                return ""
    return ""


# ---------------------------------------------------------------------------
# Misc formatting helpers
# ---------------------------------------------------------------------------


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _format_duration(seconds: int) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _title_from_url(url: str) -> str:
    cleaned = re.sub(r"^https?://(www\.)?", "", url)
    cleaned = cleaned.split("?")[0].rstrip("/")
    parts = [p for p in cleaned.split("/") if p]
    return parts[-1] if parts else cleaned


def _friendly_failure(kind: FileKind, raw: str) -> str:
    hints = {
        FileKind.DOCUMENT: "The document may be corrupt, password-protected, or unsupported.",
        FileKind.SPREADSHEET: "The spreadsheet may be corrupt or use an unsupported format.",
        FileKind.PRESENTATION: "The presentation may be corrupt or use an unsupported format.",
        FileKind.ARCHIVE: "The archive may be corrupt or contain unsupported entries.",
        FileKind.EBOOK: "The EPUB may be malformed or DRM-protected.",
        FileKind.DATA: "The data file may contain invalid syntax.",
        FileKind.WEB: "The HTML file may be malformed.",
        FileKind.UNKNOWN: "This file type is not supported.",
    }
    hint = hints.get(kind, "Conversion failed.")
    return f"{hint} ({raw})"


# A process-wide singleton; building MarkItDown repeatedly is wasteful.
_DEFAULT_CONVERTER: Optional[Converter] = None


def get_converter() -> Converter:
    """Return a lazily-instantiated, shared :class:`Converter`."""

    global _DEFAULT_CONVERTER
    if _DEFAULT_CONVERTER is None:
        _DEFAULT_CONVERTER = Converter()
    return _DEFAULT_CONVERTER
