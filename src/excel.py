"""Excel import and export for browser bookmarks with native Excel Table and summary metrics."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.formula import ArrayFormula

from .models import Bookmark, Folder


def _format_timestamp(raw_date: str) -> str:
    """Convert Unix epoch timestamp string to readable YYYY-MM-DD HH:MM:SS format."""
    if not raw_date:
        return ""
    try:
        ts = int(raw_date)
        # Handle microsecond timestamps (16+ digits)
        if ts > 100_000_000_000:
            ts = ts // 1_000_000
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return raw_date


def _parse_to_timestamp(date_val: Any) -> str:
    """Convert date object or string back to Unix epoch timestamp string."""
    if date_val is None:
        return ""
    if isinstance(date_val, (int, float)):
        return str(int(date_val))
    if isinstance(date_val, datetime):
        return str(int(date_val.timestamp()))
    
    val_str = str(date_val).strip()
    if not val_str:
        return ""
    
    # If already an integer timestamp
    if val_str.isdigit():
        return val_str
    
    # Try parsing common date formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(val_str, fmt)
            return str(int(dt.timestamp()))
        except ValueError:
            pass
    return val_str


def extract_bookmarks_with_paths(
    folder: Folder,
    current_path: str = "",
) -> list[dict[str, Any]]:
    """
    Recursively extract bookmarks with their full folder path hierarchy.
    """
    records: list[dict[str, Any]] = []

    for child in folder.children:
        if isinstance(child, Folder):
            # Do not prefix root folder title if it's generic "Bookmarks"
            if current_path:
                sub_path = f"{current_path}/{child.title}"
            else:
                sub_path = child.title if child.title != "Bookmarks" else ""
            records.extend(extract_bookmarks_with_paths(child, sub_path))
        elif isinstance(child, Bookmark):
            records.append({
                "folder_path": current_path,
                "title": child.title,
                "url": child.url,
                "raw_add_date": child.add_date,
                "formatted_date": _format_timestamp(child.add_date),
                "last_visit": child.last_visit,
                "last_modified": child.last_modified,
            })

    return records


def export_bookmarks_to_excel(
    root: Folder,
    output_path: str | Path,
    sheet_title: str = "Bookmarks",
) -> Path:
    """
    Export a bookmark Folder tree to a styled, native Excel Table with
    Row 1 summary KPIs, restore-order index [#], and analytical columns.
    """
    records = extract_bookmarks_with_paths(root)
    output_path = Path(output_path)

    # Compute URL duplicates
    url_counts = Counter(r["url"].strip().lower() for r in records if r["url"])

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title

    # -------------------------------------------------------------
    # ROW 1: Supplemental Information Details & Summary KPI Cards
    # -------------------------------------------------------------
    ws.row_dimensions[1].height = 29.25

    kpi_font = Font(name="Calibri", size=11, bold=True)
    kpi_align = Alignment(horizontal="center", vertical="center")

    ws["B1"] = "=COUNTA(Bookmarks[Bookmark Title])"
    ws["B1"].number_format = r"\T\o\t\a\l\ \B\o\o\k\m\a\r\k\s\:\ 0"

    ws["C1"] = "=MAX(Bookmarks['# Bookmarks On Domain])"
    ws["C1"].number_format = r"\M\a\x\ \B\o\o\k\m\a\r\k\s\ \O\n\ \S\i\n\g\l\e\ \D\o\m\a\i\n\:\ 0"

    ws["D1"] = "=MAX(Bookmarks[Length of Bookmark Name])"
    ws["D1"].number_format = r"\M\a\x\ \B\o\o\k\m\a\r\k\ \N\a\m\e\ \L\e\n\g\t\h\:\ 0"

    # E1: Deleted Bookmarks formula
    ws["E1"] = ArrayFormula(ref="E1", text="=MAX(Bookmarks['['#']]-COUNTA(Bookmarks[Bookmark Title]))")
    ws["E1"].number_format = r"\D\e\l\e\t\e\d\ \B\o\o\k\m\a\r\k\s\:\ 0"

    # F1: Oldest bookmark age in years & months
    ws["F1"] = (
        '="Oldest: "&ROUND((TODAY()-MIN(Bookmarks[Date Added]))/(365.25)/12,2)&" yrs. ("'
        '&ROUND((TODAY()-MIN(Bookmarks[Date Added]))/(365.25),2)&" mo.)"'
    )
    ws["F1"].number_format = "General"

    ws["G1"] = '=COUNTIF(Bookmarks[Location],"=Folder")'
    ws["G1"].number_format = r"\F\o\l\d\e\r\s\:\ 0"

    ws["H1"] = '=COUNTIF(Bookmarks[Duplicate],"=Yes*")'
    ws["H1"].number_format = r"\D\u\p\l\i\c\a\t\e\s\:\ 0"

    ws["I1"] = '=COUNTIF(Bookmarks[Location],"=Toolbar Root")'
    ws["I1"].number_format = r"\B\o\o\k\m\a\r\k\s\ \B\a\r\:\ 0"

    ws["J1"] = "=(TODAY()-MIN(Bookmarks[Date Added]))/365.25"
    ws["J1"].number_format = r"\O\l\d\e\s\t\:\ 0.00\ \m\o\."

    for col_letter in ("B", "C", "D", "E", "F", "G", "H", "I", "J"):
        cell = ws[f"{col_letter}1"]
        cell.font = kpi_font
        cell.alignment = kpi_align

    # -------------------------------------------------------------
    # ROW 2: Table Header
    # -------------------------------------------------------------
    headers = [
        "[#]",
        "Folder Path",
        "Bookmark Title",
        "URL",
        "Date Added",
        "Domain",
        "Location",
        "Duplicate",
        "Status",
        "Raw Add Date",
        "Length of Bookmark Name",
        "# Bookmarks On Domain",
    ]

    ws.row_dimensions[2].height = 45.0
    ws.append(headers)

    # -------------------------------------------------------------
    # ROW 3+: Data Rows with Structured Formulas
    # -------------------------------------------------------------
    data_font = Font(name="Calibri", size=11)
    link_font = Font(name="Calibri", size=11, color="2563EB", underline="single")
    dup_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")  # Amber highlight

    for idx, r in enumerate(records, start=1):
        row_num = idx + 2  # Table data starts at row 3
        folder_path = r["folder_path"]
        url = r["url"].strip()
        domain = urlparse(url).netloc if url else ""

        # Location detection
        is_toolbar_root = folder_path.lower() in ("bookmarks bar", "bookmarks toolbar")
        location = "Toolbar Root" if is_toolbar_root else ("Folder" if folder_path else "Root")

        # Duplicate detection
        is_dup = url_counts[url.lower()] > 1 if url else False
        dup_text = f"Yes ({url_counts[url.lower()]})" if is_dup else "No"

        date_formula = (
            '=TEXT(Bookmarks[[#This Row],[Raw Add Date]]/86400 + 25569, "yyyy-mm-dd hh:mm:ss")'
        )
        len_formula = "=LEN(Bookmarks[[#This Row],[Bookmark Title]])"
        domain_formula = "=COUNTIF(Bookmarks[Domain],Bookmarks[[#This Row],[Domain]])"

        row_data = [
            idx,  # Column 1: [#] Original listing order
            folder_path,
            r["title"],
            url,
            date_formula,
            domain,
            location,
            dup_text,
            "Keep",
            r["raw_add_date"],
            len_formula,
            domain_formula,
        ]
        ws.append(row_data)

        # Style row cells
        ws.row_dimensions[row_num].height = 20

        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=row_num, column=col_num)
            cell.font = data_font

            # Ensure all text columns are strictly string data type so Excel
            # never tries to execute strings starting with =, +, -, @ as formulas.
            if col_num in (2, 3, 4, 6, 7, 8, 9, 10):
                if isinstance(cell.value, str):
                    cell.data_type = "s"

            # Clickable URL hyperlink (capped at 2048 chars to prevent Excel corruption)
            if col_num == 4 and url.startswith(("http://", "https://")):
                if len(url) <= 2048:
                    try:
                        cell.hyperlink = url
                        cell.font = link_font
                    except Exception:
                        pass

            # Number formatting
            if col_num == 5:
                cell.number_format = r"yyyy\-mm\-dd\ hh:mm:ss;@"
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_num in (1, 7, 8, 9):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_num in (11, 12):
                cell.number_format = r'0;\(0\);* "-"_);\(@\)'
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Duplicate highlight
            if col_num == 8 and is_dup:
                cell.fill = dup_fill

    # -------------------------------------------------------------
    # CREATE NATIVE EXCEL TABLE
    # -------------------------------------------------------------
    table_max_row = max(len(records) + 2, 3)
    tab = Table(name="Bookmarks", displayName="Bookmarks", ref=f"A2:L{table_max_row}")
    tab.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium21",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(tab)

    # Freeze panes on A3 so both Row 1 (KPIs) and Row 2 (Headers) stick on scroll
    ws.freeze_panes = "A3"

    # Set column widths matching user's layout
    col_widths = {
        "A": 6.0,
        "B": 48.0,
        "C": 70.0,
        "D": 54.0,
        "E": 23.0,
        "F": 35.0,
        "G": 14.0,
        "H": 14.0,
        "I": 14.0,
        "J": 18.0,
        "K": 14.0,
        "L": 14.0,
    }
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    wb.save(output_path)
    return output_path


def import_bookmarks_from_excel(file_path: str | Path) -> Folder:
    """
    Import bookmarks from an Excel spreadsheet back into a Folder tree.
    Supports tables starting on Row 1 or Row 2.
    Skips rows where 'Status' is marked 'Delete', 'Drop', 'Remove', etc.
    Reconstructs the hierarchical folder tree.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Excel file not found: {file_path}")

    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active

    # Detect header row (search rows 1 to 5)
    header_row_idx = 1
    for r in range(1, min(6, ws.max_row + 1)):
        row_vals = [str(ws.cell(row=r, column=c).value or "").strip().lower() for c in range(1, ws.max_column + 1)]
        if any(h in row_vals for h in ("bookmark title", "title", "folder path", "url")):
            header_row_idx = r
            break

    header_row = [str(cell.value or "").strip().lower() for cell in ws[header_row_idx]]
    col_map = {name: idx for idx, name in enumerate(header_row)}

    def get_val(row, *aliases: str) -> Any:
        for alias in aliases:
            if alias in col_map:
                idx = col_map[alias]
                if idx < len(row):
                    return row[idx].value
        return None

    root = Folder(title="Bookmarks")
    # Cache created folders: path -> Folder instance
    folder_cache: dict[str, Folder] = {"": root}

    def get_or_create_folder(path_str: str) -> Folder:
        cleaned_path = path_str.strip().strip("/").strip("\\")
        if not cleaned_path:
            return root
        
        if cleaned_path in folder_cache:
            return folder_cache[cleaned_path]

        parts = [p.strip() for p in cleaned_path.replace("\\", "/").split("/") if p.strip()]
        current_folder = root
        accumulated_path = ""

        for part in parts:
            accumulated_path = f"{accumulated_path}/{part}" if accumulated_path else part
            if accumulated_path in folder_cache:
                current_folder = folder_cache[accumulated_path]
            else:
                existing = next(
                    (c for c in current_folder.children if isinstance(c, Folder) and c.title.lower() == part.lower()),
                    None,
                )
                if existing:
                    current_folder = existing
                else:
                    new_folder = Folder(title=part)
                    current_folder.children.append(new_folder)
                    current_folder = new_folder
                folder_cache[accumulated_path] = current_folder

        return current_folder

    # Read rows (starting from data row after header)
    for row in ws.iter_rows(min_row=header_row_idx + 1):
        title = get_val(row, "bookmark title", "title", "name")
        url = get_val(row, "url", "href", "link", "address")
        status = get_val(row, "status", "action", "keep/delete")

        if not url and not title:
            continue

        # Check status for deletion marks
        status_str = str(status or "").strip().lower()
        if status_str in ("delete", "del", "drop", "remove", "x", "no", "false", "0"):
            continue

        title_str = str(title or "").strip() or str(url)
        url_str = str(url or "").strip()
        folder_path = str(get_val(row, "folder path", "folder", "category") or "")

        # Extract timestamps
        raw_date = get_val(row, "raw add date")
        if raw_date is not None and str(raw_date).strip():
            add_date = str(raw_date).strip()
        else:
            date_added = get_val(row, "date added", "date", "created")
            add_date = _parse_to_timestamp(date_added)

        bookmark = Bookmark(
            title=title_str,
            url=url_str,
            add_date=add_date,
        )

        target_folder = get_or_create_folder(folder_path)
        target_folder.children.append(bookmark)

    return root
