"""Load CSV and Excel uploads into pandas DataFrames."""

from __future__ import annotations

from typing import BinaryIO

import pandas as pd

SUPPORTED_SUFFIXES = (".xlsx", ".xls", ".csv")


class FileReadError(Exception):
    """Raised when an upload cannot be parsed as a table."""


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
