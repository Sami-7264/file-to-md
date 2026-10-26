"""
whisper_transcribe.py
=====================

Local audio / video transcription using OpenAI's ``whisper`` package (no API
calls, fully offline). Whisper handles audio extraction from video containers
internally via ffmpeg, so the same code path serves both MP3/WAV and MP4/MOV.

The Whisper model is loaded lazily and cached process-wide because loading the
weights is expensive (hundreds of MB). The model size is configurable through
the ``WHISPER_MODEL`` environment variable (default: ``"base"``).
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Callable, Optional

ProgressCallback = Callable[[int, str], None]

#: Default model. Trade-off: tiny < base < small < medium < large (size/accuracy).
_DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "base")

_model = None
_model_lock = Lock()


class TranscriptionError(Exception):
    """Raised when transcription cannot be performed."""


def _load_model(name: str):
    """Load (and cache) the Whisper model. Thread-safe."""

    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:  # double-checked locking
            return _model
        try:
            import whisper  # type: ignore
        except ImportError as exc:
            raise TranscriptionError(
                "openai-whisper is not installed. "
                "Run: pip install openai-whisper  (and ensure ffmpeg is on PATH)"
            ) from exc

        try:
            _model = whisper.load_model(name)
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(
                f"Failed to load Whisper model '{name}': {exc}"
            ) from exc
    return _model


def transcribe(
    path: str | Path,
    *,
    model_name: Optional[str] = None,
    progress: Optional[ProgressCallback] = None,
) -> str:
    """Transcribe an audio or video file to plain text.

    Parameters
    ----------
    path:
        Path to the media file on the local filesystem.
    model_name:
        Override the Whisper model size for this call.
    progress:
        Optional callback ``(percent, message)`` for UI progress reporting.

    Returns
    -------
    str
        The full transcript. May be empty if no speech was detected.
    """

    path = Path(path)
    report = progress or (lambda _p, _m: None)

    if not path.exists():
        raise TranscriptionError(f"Media file not found: {path}")

    _ensure_ffmpeg()

    name = model_name or _DEFAULT_MODEL
    report(20, f"Loading Whisper model '{name}'")
    model = _load_model(name)

    report(40, "Transcribing audio (this may take a while)")
    try:
        result = model.transcribe(str(path), fp16=False, verbose=False)
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(f"Transcription failed: {exc}") from exc

    report(80, "Formatting transcript")
    return _format_segments(result)


def _format_segments(result: dict) -> str:
    """Render Whisper output as timestamped markdown paragraphs.

    Each segment becomes a line prefixed with its ``[mm:ss]`` start time, which
    keeps long transcripts navigable. Falls back to the flat ``text`` field.
    """

    segments = result.get("segments") or []
    if not segments:
        return (result.get("text") or "").strip()

    lines: list[str] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        stamp = _timestamp(seg.get("start", 0.0))
        lines.append(f"**[{stamp}]** {text}")
    return "\n\n".join(lines)


def _timestamp(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _ensure_ffmpeg() -> None:
    """Whisper shells out to ffmpeg; verify it's available with a clear error."""

    from shutil import which

    if which("ffmpeg") is None:
        raise TranscriptionError(
            "ffmpeg was not found on PATH. Whisper needs it to decode audio. "
            "Install it (macOS: 'brew install ffmpeg', Ubuntu: 'apt install ffmpeg')."
        )
