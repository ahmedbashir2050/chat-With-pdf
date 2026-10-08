"""Image extraction. Pulls every embedded raster image on a page via
PyMuPDF's image list, and links each one to the closest text block
(by vertical bbox distance) so a chunk can later be annotated with
"there's a figure near here" context — the same linkage NotebookLM-style
tools use to let a question about "the diagram on page 4" resolve to the
right figure.
"""

import fitz  # PyMuPDF

from .layout_parser import LayoutBlock
from .models import BoundingBox, ImageElement


def _closest_block(image_bbox: tuple[float, float, float, float], blocks: list[LayoutBlock]) -> LayoutBlock | None:
    if not blocks:
        return None
    img_center_y = (image_bbox[1] + image_bbox[3]) / 2
    return min(blocks, key=lambda b: abs(((b.bbox[1] + b.bbox[3]) / 2) - img_center_y))


def extract_images(
    doc: "fitz.Document",
    page: "fitz.Page",
    page_number: int,
    page_blocks: list[LayoutBlock],
    related_section: str | None,
) -> list[ImageElement]:
    images: list[ImageElement] = []

    try:
        image_list = page.get_images(full=True)
    except Exception:
        return []

    for idx, img in enumerate(image_list):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        bbox = tuple(rects[0]) if rects else (0.0, 0.0, 0.0, 0.0)

        nearby = _closest_block(bbox, page_blocks)
        nearby_text = nearby.text[:200] if nearby else None

        images.append(
            ImageElement(
                page=page_number,
                bbox=BoundingBox.from_tuple(bbox),
                image_index=idx,
                image_path=None,
                image_bytes_ref=f"xref:{xref}",
                nearby_text=nearby_text,
                related_section=related_section,
            )
        )

    return images
