"""Load CSV and Excel uploads into pandas DataFrames."""

from __future__ import annotations

import hashlib
from typing import BinaryIO

import pandas as pd

SUPPORTED_SUFFIXES = (".xlsx", ".xls", ".csv")


class FileReadError(Exception):
    """Raised when an upload cannot be parsed as a table."""


def unique_upload_name(name: str, taken: set[str]) -> str:
    """Keep two files named data.csv as data.csv and data.csv (2)."""
    if name not in taken:
        return name
    if "." in name and not name.startswith("."):
        stem, ext = name.rsplit(".", 1)
        suffix = f".{ext}"
    else:
        stem, suffix = name, ""
    i = 2
    while True:
        candidate = f"{stem} ({i}){suffix}"
        if candidate not in taken:
            return candidate
        i += 1
    """Short content hash so a same-shaped replacement file still resets session."""
    return hashlib.sha256(data).hexdigest()[:16]


def _read_csv(file: BinaryIO) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            file.seek(0)
            return pd.read_csv(file, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
        except pd.errors.EmptyDataError as exc:
            raise FileReadError("The CSV file is empty.") from exc
        except Exception as exc:  # pandas parser errors, etc.
            last_error = exc
            break
    raise FileReadError(f"Could not read CSV: {last_error}") from last_error


def read_uploaded_file(file) -> pd.DataFrame:
    """Read a Streamlit UploadedFile (.csv / .xlsx / .xls)."""
    name = (file.name or "").lower()
    try:
        file.seek(0)
        if name.endswith(".csv"):
            df = _read_csv(file)
        elif name.endswith(".xlsx"):
            df = pd.read_excel(file, engine="openpyxl")
        elif name.endswith(".xls"):
            df = pd.read_excel(file, engine="xlrd")
        else:
            raise FileReadError(
                f"Unsupported file type: {file.name}. Use .csv, .xlsx, or .xls."
            )
    except FileReadError:
        raise
    except Exception as exc:
        raise FileReadError(f"Could not read '{file.name}': {exc}") from exc

    if df is None or df.empty:
        raise FileReadError(
            f"'{file.name}' has no rows. Upload a file that contains data."
        )
    if len(df.columns) == 0:
        raise FileReadError(f"'{file.name}' has no columns.")
    return df


def merge_frames(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, bool]:
    """Stack files row-wise. Returns (merged, headers_differ)."""
    header_sets = [tuple(map(str, f.columns)) for f in frames.values()]
    headers_differ = len(set(header_sets)) > 1
    pieces = []
    for name, frame in frames.items():
        piece = frame.copy()
        piece.insert(0, "_source_file", name)
        pieces.append(piece)
    merged = pd.concat(pieces, ignore_index=True, sort=False)
    return merged, headers_differ


_FORMULA_PREFIXES = frozenset("=+-@\t\r")


def _neutralize_cell(value):
    if not isinstance(value, str) or not value:
        return value
    lead = value.lstrip(" \t\r\n")
    if lead and lead[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def neutralize_formula_cells(df: pd.DataFrame) -> pd.DataFrame:
    """Stop Excel/Sheets from treating exported text as formulas."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]) or pd.api.types.is_datetime64_any_dtype(
            out[col]
        ):
            continue
        out[col] = out[col].map(_neutralize_cell)
    return out
