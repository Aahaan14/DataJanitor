"""
DataJanitor — CSV ingestion service.

Responsibilities: filename checks, size-limited reading, encoding detection,
delimiter detection, parsing and saving the untouched original upload.

Design decisions
────────────────
• Every cell is parsed as *text* (dtype=str). Letting pandas guess types at
  load time would silently turn "007" into 7 or "N/A" into NaN — i.e. modify
  the user's data before we even look at it. Type inference is done later,
  read-only, in profiling_service.
• Only truly empty cells count as missing at this stage; strings like "NA"
  or "null" are kept verbatim so Phase 3 can report them as suspicious.
• The original bytes are saved exactly as received, under a random UUID
  filename. The user-supplied filename is never used as a path.
"""

import csv
import io
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import chardet
import pandas as pd
from fastapi import UploadFile

from app.core.exceptions import (
    DatasetLimitError,
    EmptyFileError,
    EncodingError,
    FileTooLargeError,
    InvalidFileTypeError,
    MalformedCSVError,
)

ALLOWED_EXTENSION = ".csv"
SUPPORTED_DELIMITERS = ",;\t|"
CHUNK_SIZE = 64 * 1024
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._ \-()]")


def sanitize_filename(filename: str | None) -> str:
    """
    Validate the extension and return a display-safe filename.

    Strips any directory components (both / and \\ styles) and unsafe
    characters. The result is only for display — never used as a path.
    """
    if not filename or not filename.strip():
        raise InvalidFileTypeError("No filename was provided.")
    base = re.split(r"[\\/]", filename)[-1].strip()
    if not base.lower().endswith(ALLOWED_EXTENSION):
        raise InvalidFileTypeError("Only .csv files are accepted.")
    safe = _UNSAFE_CHARS.sub("_", base)[:150]
    if safe.lower() == ALLOWED_EXTENSION:  # e.g. ".csv" alone
        raise InvalidFileTypeError("The filename is not valid.")
    return safe


async def read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks, aborting as soon as the size limit is hit."""
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FileTooLargeError(
                f"File exceeds the maximum size of {max_bytes // (1024 * 1024)} MB."
            )
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw.strip():
        raise EmptyFileError("The uploaded file is empty.")
    return raw


def decode_bytes(raw: bytes) -> Tuple[str, str, List[str]]:
    """
    Decode raw bytes to text. Returns (text, encoding_name, warnings).

    Order: BOM → UTF-8 → chardet guess → Windows-1252. Files containing
    NUL bytes without a UTF-16 BOM are rejected as binary.
    """
    warnings: List[str] = []

    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig", warnings
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16"), "utf-16", warnings
        except UnicodeDecodeError as exc:
            raise EncodingError("The UTF-16 file could not be decoded.") from exc

    if b"\x00" in raw[:8192]:
        raise EncodingError(
            "The file looks like binary data, not a text CSV."
        )

    try:
        return raw.decode("utf-8"), "utf-8", warnings
    except UnicodeDecodeError:
        pass

    guess = chardet.detect(raw[:100_000])
    candidates = []
    if guess.get("encoding") and (guess.get("confidence") or 0) >= 0.5:
        candidates.append(guess["encoding"])
    candidates.append("cp1252")
    for enc in candidates:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        warnings.append(
            f"File is not UTF-8; decoded as {enc}. Check that accented "
            "characters look correct."
        )
        return text, enc, warnings

    raise EncodingError(
        "Could not determine the file's text encoding. "
        "Please re-save it as UTF-8 and upload again."
    )


def detect_delimiter(text: str) -> str:
    """Sniff the delimiter from the first lines; default to a comma."""
    sample = "\n".join(text.splitlines()[:20])[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=SUPPORTED_DELIMITERS).delimiter
    except csv.Error:
        return ","


def parse_csv(
    text: str, delimiter: str, max_rows: int, max_columns: int
) -> Tuple[pd.DataFrame, List[str]]:
    """Parse CSV text into an all-string DataFrame, enforcing size limits."""
    warnings: List[str] = []
    try:
        df = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
            on_bad_lines="error",
            nrows=max_rows + 1,
        )
    except pd.errors.EmptyDataError as exc:
        raise EmptyFileError("The file contains no CSV data.") from exc
    except (pd.errors.ParserError, csv.Error) as exc:
        # pandas messages name the offending line, which is useful and safe.
        raise MalformedCSVError(f"The CSV is malformed: {exc}") from exc

    if df.shape[1] > max_columns:
        raise DatasetLimitError(
            f"The dataset has {df.shape[1]} columns; the limit is {max_columns}."
        )
    if len(df) > max_rows:
        raise DatasetLimitError(f"The dataset has more than {max_rows} rows.")
    if df.empty:
        raise EmptyFileError("The CSV has a header but no data rows.")

    unnamed = [c for c in df.columns if str(c).startswith("Unnamed:")]
    if unnamed:
        warnings.append(
            f"{len(unnamed)} column(s) have no header name and were labelled "
            "automatically (Unnamed: N)."
        )
    dup = [c for c in df.columns if re.search(r"\.\d+$", str(c))]
    if dup:
        warnings.append(
            "Duplicate column names were detected; later copies were renamed "
            "with a numeric suffix (e.g. name.1)."
        )
    return df, warnings


def save_original(raw: bytes, upload_dir: Path) -> Tuple[str, Path]:
    """
    Persist the original bytes unchanged as <uuid>.csv.

    Written to a temp file first, then atomically renamed, so a crash can
    never leave a half-written file that looks like a valid upload.
    """
    upload_dir.mkdir(parents=True, exist_ok=True)
    dataset_id = uuid.uuid4().hex
    final_path = upload_dir / f"{dataset_id}.csv"
    fd, tmp_name = tempfile.mkstemp(dir=upload_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        os.replace(tmp_name, final_path)
    except OSError:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return dataset_id, final_path


@dataclass
class ParsedCSV:
    df: pd.DataFrame
    encoding: str
    delimiter: str
    warnings: List[str]
    header: List[str]  # header exactly as written in the file (pandas may rename duplicates)


def _read_header(text: str, delimiter: str) -> List[str]:
    for record in csv.reader(io.StringIO(text), delimiter=delimiter):
        if record:  # skip leading blank lines, like the pandas parser does
            return record
    return []


def parse_bytes(raw: bytes, max_rows: int, max_columns: int) -> ParsedCSV:
    """Decode + sniff + parse in one step (shared by upload and scan)."""
    text, encoding, enc_warnings = decode_bytes(raw)
    delimiter = detect_delimiter(text)
    df, parse_warnings = parse_csv(text, delimiter, max_rows, max_columns)
    header = _read_header(text, delimiter)
    if len(header) != df.shape[1]:
        header = [str(c) for c in df.columns]  # defensive fallback
    return ParsedCSV(df, encoding, delimiter, enc_warnings + parse_warnings, header)
