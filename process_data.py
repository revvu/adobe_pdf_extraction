import argparse
import json
import re
import sys
import textwrap
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

def load_structured_data(zip_path: str) -> Dict:
    """Load the first JSON payload contained in the extraction zip."""
    with zipfile.ZipFile(zip_path, "r") as archive:
        json_members = [name for name in archive.namelist() if name.lower().endswith(".json")]
        if not json_members:
            raise ValueError("No JSON members found in the provided zip file.")
        member = sorted(json_members)[0]
        return json.loads(archive.read(member))


def parse_segment(segment: str) -> Tuple[str, int]:
    """Break a segment like TD[3] into its base name and 1-based index."""
    match = re.match(r"(?P<name>[A-Za-z]+)(?:\[(?P<index>\d+)\])?$", segment)
    if not match:
        return segment, 1
    name = match.group("name")
    index = int(match.group("index") or "1")
    return name, index


def normalize_fragment(text: str) -> str:
    """Collapse whitespace while keeping the original token order."""
    cleaned = re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()
    return cleaned


def current_heading_title(heading_by_level: Dict[int, str]) -> Optional[str]:
    """Return the deepest heading that has been seen so far."""
    if not heading_by_level:
        return None
    deepest_level = max(heading_by_level)
    return heading_by_level[deepest_level]


def extract_tables(elements: List[Dict]) -> List[Dict]:
    """Iterate through elements and assemble table structures."""
    table_pattern = re.compile(r"/Table(\[\d+\])?")
    heading_pattern = re.compile(r"(.*?/H([1-6])(?:\[\d+\])?)")

    heading_fragments: Dict[str, List[str]] = defaultdict(list)
    heading_by_level: Dict[int, str] = {}

    tables: Dict[str, Dict] = {}
    table_order: List[str] = []

    for element in elements:
        path = element["Path"]
        text = element.get("Text", "")

        # Track the most recent heading so we can label tables with it.
        if text:
            heading_match = heading_pattern.search(path)
            if heading_match:
                heading_path = heading_match.group(1)
                level = int(heading_match.group(2))
                fragment = normalize_fragment(text)
                if fragment:
                    fragments = heading_fragments[heading_path]
                    if not fragments or fragments[-1] != fragment:
                        fragments.append(fragment)
                    heading_by_level[level] = " ".join(fragments)
                    # Any headings deeper than this level no longer apply.
                    for deeper in [lvl for lvl in heading_by_level if lvl > level]:
                        heading_by_level.pop(deeper, None)

        table_match = table_pattern.search(path)
        if not table_match:
            continue

        table_root = path[: table_match.end()]
        if table_root not in tables:
            tables[table_root] = {
                "id": table_root,
                "title": current_heading_title(heading_by_level),
                "page": element.get("Page"),
                "attributes": {},
                "cells": defaultdict(lambda: defaultdict(list)),
                "row_meta": defaultdict(lambda: {"has_th": False, "has_td": False}),
                "column_order": defaultdict(dict),
            }
            table_order.append(table_root)

        table = tables[table_root]
        if table.get("page") is None and element.get("Page") is not None:
            table["page"] = element.get("Page")

        # Capture table level metadata if present.
        if path == table_root:
            attrs = element.get("attributes")
            if attrs:
                table["attributes"] = attrs
            if table.get("title") is None:
                table["title"] = current_heading_title(heading_by_level)
            continue

        if "Text" not in element:
            continue

        remainder = path[table_match.end() :]
        segments = [seg for seg in remainder.split("/") if seg]

        row_index: Optional[int] = None
        col_index: Optional[int] = None
        col_type: Optional[str] = None

        for segment in segments:
            name, idx = parse_segment(segment)
            if name == "TR":
                row_index = idx
            elif name in {"TD", "TH"}:
                col_index = idx
                col_type = name

        if row_index is None or col_index is None or col_type is None:
            continue

        fragment = normalize_fragment(text)
        if not fragment:
            continue
        column_order = table["column_order"][row_index]
        cell_key = (col_type, col_index)
        if cell_key not in column_order:
            column_order[cell_key] = len(column_order) + 1
        col_position = column_order[cell_key]

        table["cells"][row_index][col_position].append(fragment)
        row_meta = table["row_meta"][row_index]
        if col_type == "TH":
            row_meta["has_th"] = True
        else:
            row_meta["has_td"] = True

    return [tables[key] for key in table_order]


def assemble_rows(table: Dict) -> Tuple[List[List[str]], int]:
    """Convert collected cell fragments into ordered rows."""
    cells = table["cells"]
    attributes = table.get("attributes", {})
    declared_cols = attributes.get("NumCol", 0)

    observed_cols = 0
    for cols in cells.values():
        if cols:
            observed_cols = max(observed_cols, max(cols.keys()))

    num_cols = max(declared_cols, observed_cols)
    if num_cols == 0:
        return [], 0

    ordered_rows: List[List[str]] = []
    header_rows = 0
    header_phase = True

    for row_index in sorted(cells.keys()):
        row_cells = cells[row_index]
        row_values = []
        for col_idx in range(1, num_cols + 1):
            fragments = row_cells.get(col_idx, [])
            value = " ".join(fragments).strip()
            row_values.append(value)

        if header_phase:
            meta = table["row_meta"].get(row_index, {})
            is_header = meta.get("has_th") and not meta.get("has_td")
            if is_header:
                header_rows += 1
            else:
                header_phase = False
        ordered_rows.append(row_values)

    # Drop trailing columns that are empty in every row for readability.
    last_non_empty = -1
    for col_idx in range(num_cols):
        if any(row[col_idx] for row in ordered_rows):
            last_non_empty = col_idx

    if last_non_empty >= 0:
        ordered_rows = [row[: last_non_empty + 1] for row in ordered_rows]
    else:
        ordered_rows = [[] for _ in ordered_rows]

    return ordered_rows, header_rows


def compute_column_widths(rows: List[List[str]]) -> List[int]:
    """Determine column widths with sane upper and lower bounds."""
    if not rows:
        return []

    num_cols = max(len(row) for row in rows)
    widths = [3] * num_cols

    for col_idx in range(num_cols):
        longest = 0
        for row in rows:
            if col_idx >= len(row):
                continue
            cell = row[col_idx]
            if not cell:
                continue
            for line in cell.splitlines():
                longest = max(longest, len(line))
        widths[col_idx] = max(3, min(longest, 36))

    return widths


def wrap_cell(text: str, width: int) -> List[str]:
    """Wrap a cell's text to the provided width."""
    if width <= 0:
        return [text]
    lines = textwrap.wrap(text, width=width, replace_whitespace=False) or [""]
    return lines


def render_table(rows: List[List[str]], header_rows: int, out=None) -> None:
    """Pretty-print a table as an ASCII grid."""
    stream = out or sys.stdout
    if not rows:
        print("  (no textual data)", file=stream)
        return

    widths = compute_column_widths(rows)
    if not widths:
        print("  (no textual data)", file=stream)
        return

    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    header_border = "+" + "+".join("=" * (width + 2) for width in widths) + "+"

    def emit_row(row: List[str]) -> None:
        wrapped = []
        for col_idx, width in enumerate(widths):
            cell = row[col_idx] if col_idx < len(row) else ""
            wrapped.append(wrap_cell(cell, width))

        max_lines = max(len(lines) for lines in wrapped)
        for line_index in range(max_lines):
            pieces = []
            for col_idx, width in enumerate(widths):
                lines = wrapped[col_idx]
                fragment = lines[line_index] if line_index < len(lines) else ""
                pieces.append(f" {fragment.ljust(width)} ")
            print("|" + "|".join(pieces) + "|", file=stream)

    print(border, file=stream)
    for idx, row in enumerate(rows):
        emit_row(row)
        is_last = idx == len(rows) - 1
        if header_rows and idx == header_rows - 1:
            print(header_border if not is_last else border, file=stream)
        else:
            print(border, file=stream)


def print_tables(tables: List[Dict], out=None) -> None:
    """Print each table with its inferred title."""
    stream = out or sys.stdout
    for idx, table in enumerate(tables, start=1):
        title = table.get("title") or f"Table {idx}"
        page = table.get("page")
        header = f"Table {idx}: {title}"
        if page is not None:
            header += f" (Page {page})"
        print(header, file=stream)
        rows, header_rows = assemble_rows(table)
        render_table(rows, header_rows, out=stream)
        print(file=stream)


def export_tables_to_json(tables: List[Dict], output_path: Path) -> None:
    """Write all tables to a single JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tables": []}
    for idx, table in enumerate(tables, start=1):
        title = table.get("title") or f"Table {idx}"
        rows, header_rows = assemble_rows(table)
        payload["tables"].append(
            {
                "table_index": idx,
                "title": title,
                "page": table.get("page"),
                "attributes": table.get("attributes", {}),
                "rows": rows,
            }
        )
    output_path.write_text(json.dumps(payload, indent=2))


def export_tables_sample_json(tables: List[Dict], output_path: Path) -> None:
    """Write a sample JSON containing truncated copies of each table."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tables": []}
    for idx, table in enumerate(tables, start=1):
        title = table.get("title") or f"Table {idx}"
        rows, header_rows = assemble_rows(table)
        preview_rows = []
        if rows:
            header_rows = max(header_rows, 0)
            header_part = rows[:header_rows]
            data_part = rows[header_rows : header_rows + 5]
            preview_rows = header_part + data_part

        attributes = table.get("attributes", {})
        sample_attributes = {
            key: attributes[key]
            for key in ("NumCol", "NumRow")
            if key in attributes
        }

        payload["tables"].append(
            {
                "table_index": idx,
                "title": title,
                "page": table.get("page"),
                "attributes": sample_attributes,
                "rows": preview_rows,
            }
        )
    output_path.write_text(json.dumps(payload, indent=2))


def write_tables_text(tables: List[Dict], output_path: Path) -> None:
    """Persist the pretty-printed tables to a text file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        print_tables(tables, out=handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render and export tables from Adobe PDF extract output.")
    parser.add_argument(
        "directory",
        help="Directory containing extract.zip; outputs will be written here too.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = Path(args.directory)
    zip_path = base_dir / "extract.zip"
    json_output_path = base_dir / "tables.json"
    sample_output_path = base_dir / "sample_tables.json"
    text_output_path = base_dir / "tables.txt"

    if not zip_path.exists():
        raise FileNotFoundError(f"Expected extract.zip at {zip_path}. Run extract.py or adjust the directory.")

    data = load_structured_data(zip_path)
    tables = extract_tables(data["elements"])
    if not tables:
        text_output_path.parent.mkdir(parents=True, exist_ok=True)
        text_output_path.write_text("No tables found in the structured data.\n", encoding="utf-8")
        return
    write_tables_text(tables, text_output_path)
    export_tables_to_json(tables, json_output_path)
    export_tables_sample_json(tables, sample_output_path)


if __name__ == "__main__":
    main()
