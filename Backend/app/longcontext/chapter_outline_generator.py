"""ChapterOutlineGenerator (spec item 6). Deliberately NOT an LLM call —
the chapter/section/subsection/heading fields on each `DocumentChunk`
(populated by Phase 2's hierarchy detection) already ARE the document's
own outline; generating it is a matter of walking the chunks in page
order and recording each place a heading field changes, not asking a
model to reconstruct something already sitting in structured form. This
is faster, free, and exactly matches the source document's actual
structure rather than an LLM's paraphrase of it.
"""

from dataclasses import dataclass, field

from ..domain.entities import DocumentChunk


@dataclass
class OutlineEntry:
    level: str  # 'section' | 'subsection' | 'heading'
    text: str
    page: int  # physical page — `render_markdown` below doesn't currently display it, but it's the
    # only page identity this outline entry carries (no page_label: `render_markdown` never read
    # it, and it would never be citation-relevant metadata anyway — see domain/citations.py)


@dataclass
class ChapterOutline:
    chapter: str | None
    entries: list[OutlineEntry] = field(default_factory=list)


class ChapterOutlineGenerator:
    def generate(self, chapter_chunks: list[DocumentChunk]) -> ChapterOutline:
        if not chapter_chunks:
            return ChapterOutline(chapter=None, entries=[])

        ordered = sorted(
            chapter_chunks,
            key=lambda c: (c.page, c.paragraph_index if c.paragraph_index is not None else 0),
        )
        chapter_label = ordered[0].chapter

        entries: list[OutlineEntry] = []
        seen: set[tuple[str, str]] = set()  # (level, text) — dedupe consecutive/repeated headings across chunks

        for c in ordered:
            for level, text in (("section", c.section), ("subsection", c.subsection), ("heading", c.heading)):
                if not text:
                    continue
                key = (level, text)
                if key in seen:
                    continue
                seen.add(key)
                entries.append(OutlineEntry(level=level, text=text, page=c.page))

        return ChapterOutline(chapter=chapter_label, entries=entries)

    @staticmethod
    def render_markdown(outline: ChapterOutline) -> str:
        """A simple numbered rendering matching the spec's own example
        format ("1. Introduction / 2. Neural Networks / ..."). Useful for
        directly showing an outline to a user without an LLM call."""
        if not outline.entries:
            return f"{outline.chapter or 'This chapter'}: no structural headings were detected."

        lines = [f"# {outline.chapter}"] if outline.chapter else []
        counter = 0
        for entry in outline.entries:
            if entry.level == "section":
                counter += 1
                lines.append(f"{counter}. {entry.text}")
            elif entry.level == "subsection":
                lines.append(f"   - {entry.text}")
            else:
                lines.append(f"   • {entry.text}")
        return "\n".join(lines)
