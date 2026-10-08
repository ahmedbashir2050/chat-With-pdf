"""Table extraction via PyMuPDF's built-in table finder
(`page.find_tables()`, available in PyMuPDF >= 1.23). Guarded with
`getattr`/try-except rather than a hard import check, since the pinned
version in requirements.txt may lag — on older PyMuPDF this simply
degrades to "no tables extracted" instead of crashing the whole parse.
"""

import fitz  # PyMuPDF

from .models import BoundingBox, TableElement


def _table_to_markdown(rows: list[list[str | None]]) -> str | None:
    if not rows:
        return None

    cleaned = [[(cell or "").strip().replace("\n", " ") for cell in row] for row in rows]
    header, *body = cleaned
    if not any(header):
        return None

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        # Pad/truncate ragged rows to the header width so the markdown
        # table stays well-formed even if PyMuPDF's cell count varies.
        row = (row + [""] * len(header))[: len(header)]
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def extract_tables(page: "fitz.Page", page_number: int, related_section: str | None) -> list[TableElement]:
    finder = getattr(page, "find_tables", None)
    if finder is None:
        return []

    try:
        found = finder()
    except Exception:
        return []

    tables: list[TableElement] = []
    for table in getattr(found, "tables", []):
        try:
            rows = table.extract()
        except Exception:
            continue

        markdown = _table_to_markdown(rows)
        if not markdown:
            continue

        tables.append(
            TableElement(
                page=page_number,
                bbox=BoundingBox.from_tuple(tuple(table.bbox)),
                markdown_content=markdown,
                related_section=related_section,
            )
        )

    return tables
