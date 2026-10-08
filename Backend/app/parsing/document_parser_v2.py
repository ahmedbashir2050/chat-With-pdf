"""The Phase 2 document-intelligence parser. `DocumentIntelligenceParser`
still implements `domain.interfaces.DocumentParser` (i.e. it still has an
`extract_chunks(pdf_bytes, chat_id, chunk_size)` method with the exact
same signature the original `PyMuPDFDocumentParser` had) — so it's a
drop-in replacement at the composition root (`api/deps.py`) with zero
changes required to `ChatService` or anything downstream. `extract_chunks`
internally calls `extract_document` and flattens the result via
`adapter.to_legacy_chunks`.

`extract_document` is the new, richer entry point — it's what a future
endpoint wanting the full structure (outline view, table/image browsing)
would call directly.

Per-page extraction (spec: page classification + quality gate + safe
fallback). Every page now goes through:

    parse_page_layout -> extract_page_signals -> classify_page
        -> (SCANNED/CORRUPTED: OCR, with a bounded, DPI-escalating retry
            loop gated by quality_gate.assess_page_quality)
        -> (MIXED: native text kept as-is — region-level OCR of the
            image portion is a documented follow-up, not yet
            implemented; see `_extract_page`'s docstring)
        -> (NATIVE/EMPTY: native text used as-is)

replacing the old, single-signal "if not layout_page.blocks: OCR" rule,
which trusted any native text that existed at all (including corrupted/
garbled text) and never OCR'd a page that had SOME native text but was
mostly a scanned image. A page whose quality gate ends in `failed` (or
`needs_review`, unless `settings.include_needs_review_in_rag`) has its
blocks excluded from chunking/embedding entirely — its extracted text is
kept on `ParsedPage.raw_text` for review, never silently indexed.

Physical page numbering is unchanged throughout: `page_number = i + 1`,
1-based, exactly as before this change — see `tests/test_page_number_
invariants.py` for the regression tests locking this down.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import fitz  # PyMuPDF

from ..config import settings
from ..domain.entities import DocumentChunk
from ..domain.interfaces import OCRService
from . import adapter
from .hierarchy import build_hierarchy_tree, classify_blocks
from .image_extractor import extract_images
from .language import detect_document_language, detect_language
from .layout_parser import LayoutBlock, parse_page_layout
from .models import DocumentMetadata, ParsedDocument, ParsedPage
from .page_classifier import ClassifierConfig, PageClass, PageSignals, classify_page, extract_page_signals
from .page_labels import build_catalog_label_map, detect_page_label
from .quality_gate import QualityAssessment, QualityGateConfig, QualityStatus, SourceType, assess_page_quality
from .semantic_chunker import chunk_document
from .table_extractor import extract_tables

# Existing default for a normal (non-retry) OCR rasterization — unchanged
# from before this change. Retries escalate from `settings.quality_ocr_retry_dpi`
# (default 300) and step up further on each subsequent bounded retry.
_INITIAL_OCR_DPI = 200
_RETRY_DPI_STEP = 100
_RETRY_DPI_MAX = 600


def _pdf_date_to_iso(raw: str | None) -> str | None:
    """PDF date strings look like D:20230114120000+02'00'. Best-effort
    parse; falls back to returning the raw string unchanged so metadata
    extraction never fails a whole parse over a malformed date."""
    if not raw:
        return None
    value = raw[2:] if raw.startswith("D:") else raw
    try:
        return datetime.strptime(value[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return raw


@dataclass
class _PageExtraction:
    """Everything one page's classify -> gate -> (maybe retry) pass
    produces — what `_extract_page` returns and `extract_document`'s
    loop consumes to build both the chunk-feeding block list and the
    per-page `ParsedPage` record."""

    blocks: list[LayoutBlock]  # empty if excluded_from_rag
    raw_text: str | None  # only populated when excluded_from_rag, for review
    is_two_column: bool
    classification: PageClass
    quality_status: QualityStatus
    quality_score: float | None
    warnings: list[str]
    retry_count: int
    retry_reasons: list[str]
    source_type: SourceType
    excluded_from_rag: bool


class DocumentIntelligenceParser:
    """Implements domain.interfaces.DocumentParser."""

    def __init__(
        self,
        ocr_service: OCRService,
        classifier_config: ClassifierConfig | None = None,
        quality_config: QualityGateConfig | None = None,
    ):
        self._ocr = ocr_service
        # Built from `settings` by default so the env-var thresholds
        # actually take effect; constructor params exist so tests (and
        # any future per-deployment override) don't have to mutate the
        # global `settings` singleton to exercise a different threshold.
        self._classifier_config = classifier_config or ClassifierConfig(
            min_native_chars=settings.page_min_native_chars,
            min_native_words=settings.page_min_native_words,
            image_coverage_threshold=settings.page_image_coverage_threshold,
            suspicious_char_rate_threshold=settings.page_suspicious_char_rate_threshold,
            trivial_image_coverage=settings.page_trivial_image_coverage,
            min_plausible_avg_word_length=settings.page_min_plausible_avg_word_length,
        )
        self._quality_config = quality_config or QualityGateConfig(
            accept_score_threshold=settings.quality_accept_score_threshold,
            retry_score_threshold=settings.quality_retry_score_threshold,
            review_score_threshold=settings.quality_review_score_threshold,
            max_retries=settings.quality_max_retries,
        )

    # ---- existing protocol method: unchanged signature, richer internals ----
    def extract_chunks(self, pdf_bytes: bytes, chat_id: int, chunk_size: int = 800) -> list[DocumentChunk]:
        parsed = self.extract_document(pdf_bytes, chat_id)
        return adapter.to_legacy_chunks(parsed)

    # ---- new Phase 2 entry point ----
    def extract_document(self, pdf_bytes: bytes, chat_id: int) -> ParsedDocument:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        document_id = str(uuid.uuid4())

        try:
            catalog_labels = build_catalog_label_map(doc)
            all_blocks = []
            parsed_pages: list[ParsedPage] = []
            page_quality_map: dict[int, _PageExtraction] = {}
            all_tables = []
            all_images = []
            page_languages: list[str | None] = []

            for i, page in enumerate(doc):
                page_number = i + 1  # 1-based physical page index — see module docstring; never changed
                extraction = self._extract_page(page, page_number)
                page_quality_map[page_number] = extraction

                page_text = "\n".join(b.text for b in extraction.blocks)
                page_lang = detect_language(page_text)
                page_languages.append(page_lang)

                # Detected printed page label — kept as page-level metadata
                # only (e.g. a future table-of-contents/"page iv" display
                # feature). It is NEVER threaded onto chunks or citations
                # — see domain/citations.py: the only citation page field
                # anywhere in this project is the physical page number.
                label = detect_page_label(page, catalog_labels, i)

                parsed_pages.append(
                    ParsedPage(
                        page=page_number,
                        page_label=label,
                        language=page_lang,
                        is_two_column=extraction.is_two_column,
                        has_ocr_fallback=extraction.source_type != SourceType.NATIVE,
                        classification=extraction.classification.value,
                        quality_status=extraction.quality_status.value,
                        quality_score=extraction.quality_score,
                        quality_warnings=extraction.warnings,
                        retry_count=extraction.retry_count,
                        retry_reasons=extraction.retry_reasons,
                        source_type=extraction.source_type.value,
                        excluded_from_rag=extraction.excluded_from_rag,
                        raw_text=extraction.raw_text,
                    )
                )

                all_blocks.extend(extraction.blocks)  # already [] when excluded_from_rag

                related_section = None  # filled in properly during chunking; tables/images use page-level context here
                all_tables.extend(extract_tables(page, page_number, related_section))
                all_images.extend(extract_images(doc, page, page_number, extraction.blocks, related_section))

            classified = classify_blocks(all_blocks)
            hierarchy = build_hierarchy_tree(classified)
            chunks = chunk_document(classified, chat_id=chat_id, document_id=document_id)
            self._tag_chunk_quality(chunks, page_quality_map)

            metadata = self._extract_metadata(doc, document_id, page_languages)

            return ParsedDocument(
                metadata=metadata,
                pages=parsed_pages,
                hierarchy=hierarchy,
                chunks=chunks,
                tables=all_tables,
                images=all_images,
            )
        finally:
            doc.close()

    # ---- per-page classify -> gate -> (maybe retry) ----

    def _extract_page(self, page: "fitz.Page", page_number: int) -> _PageExtraction:
        layout_page = parse_page_layout(page, page_number)
        signals = extract_page_signals(page, layout_page.blocks)
        result = classify_page(signals, self._classifier_config)
        classification = result.classification
        warnings = list(result.warnings)

        if classification in (PageClass.SCANNED, PageClass.CORRUPTED):
            return self._extract_via_ocr(page, page_number, classification, warnings, layout_page.is_two_column)

        if classification == PageClass.MIXED:
            # Native text is reliable by definition of this classification
            # (it cleared the same char/word/corruption checks a NATIVE
            # page does) — kept as-is. Region-level OCR of the image
            # portion specifically (spec: "OCR only image regions that
            # lack reliable native text") is a deliberate, documented gap
            # in this pass, not a silent omission: flagged as a warning
            # so it's visible in `ParsedPage.quality_warnings` and in the
            # final report, rather than claiming full coverage this phase
            # doesn't actually implement yet.
            warnings.append(
                "page classified MIXED (native text + a significant embedded image region); "
                "only the native text was indexed — region-level OCR of the image portion is "
                "not yet implemented (tracked as a follow-up, not silently skipped)"
            )
            assessment = assess_page_quality(
                signals, classification, warnings, SourceType.NATIVE, ocr_confidence=None, config=self._quality_config
            )
            return self._finalize(layout_page.blocks, layout_page.is_two_column, assessment)

        # NATIVE or EMPTY
        assessment = assess_page_quality(
            signals, classification, warnings, SourceType.NATIVE, ocr_confidence=None, config=self._quality_config
        )
        return self._finalize(layout_page.blocks, layout_page.is_two_column, assessment)

    def _extract_via_ocr(
        self,
        page: "fitz.Page",
        page_number: int,
        classification: PageClass,
        warnings: list[str],
        is_two_column: bool,
    ) -> _PageExtraction:
        retry_reasons: list[str] = []
        if classification == PageClass.CORRUPTED:
            # Corrupted native text is untrustworthy by definition (a
            # broken font/CMap) — retrying the same native extraction
            # would return the same broken result, so the correct "retry
            # strategy" here is to fall back to OCR immediately, exactly
            # as for a scanned page, not to re-attempt native extraction.
            retry_reasons.append(f"native extraction corrupted ({'; '.join(warnings) or 'see warnings'}); using OCR instead")

        dpi = _INITIAL_OCR_DPI
        retry_count = 0
        blocks, signals = self._ocr_full_page(page, page_number, dpi)
        assessment = assess_page_quality(
            signals,
            PageClass.SCANNED,  # score/gate the OCR'd result on its own terms regardless of the original classification
            warnings,
            SourceType.OCR,
            ocr_confidence=None,  # VisionOCRService doesn't expose one — never fabricated (spec item 8)
            retry_count=retry_count,
            retry_reasons=retry_reasons,
            config=self._quality_config,
        )

        while assessment.status == QualityStatus.NEEDS_RETRY:
            retry_count += 1
            dpi = min(_RETRY_DPI_MAX, max(settings.quality_ocr_retry_dpi, dpi + _RETRY_DPI_STEP))
            retry_reasons.append(
                f"retry {retry_count}: re-rendering at {dpi} DPI "
                f"(previous attempt scored {assessment.score if assessment.score is not None else 'N/A'})"
            )
            blocks, signals = self._ocr_full_page(page, page_number, dpi)
            assessment = assess_page_quality(
                signals,
                PageClass.SCANNED,
                warnings,
                SourceType.OCR,
                ocr_confidence=None,
                retry_count=retry_count,
                retry_reasons=retry_reasons,
                config=self._quality_config,
            )

        return self._finalize(blocks, is_two_column, assessment, force_source_type=SourceType.OCR)

    def _ocr_full_page(self, page: "fitz.Page", page_number: int, dpi: int) -> tuple[list[LayoutBlock], PageSignals]:
        pix = page.get_pixmap(dpi=dpi)
        text = self._ocr.transcribe_page_image(pix.tobytes("png")).strip()
        blocks = [self._ocr_block(page, page_number, text)] if text else []
        signals = extract_page_signals(page, blocks)
        return blocks, signals

    @staticmethod
    def _ocr_block(page: "fitz.Page", page_number: int, text: str) -> LayoutBlock:
        return LayoutBlock(
            page=page_number,
            block_index=0,
            text=text,
            bbox=(0.0, 0.0, page.rect.width, page.rect.height),
            max_font_size=0.0,
            avg_font_size=0.0,
            is_bold=False,
        )

    @staticmethod
    def _finalize(
        blocks: list[LayoutBlock],
        is_two_column: bool,
        assessment: QualityAssessment,
        force_source_type: SourceType | None = None,
    ) -> "_PageExtraction":
        excluded = assessment.status == QualityStatus.FAILED or (
            assessment.status == QualityStatus.NEEDS_REVIEW and not settings.include_needs_review_in_rag
        )
        raw_text = None
        final_blocks = blocks
        if excluded:
            # Preserve the extracted text for review (spec: "Keep
            # original extracted text and provenance") — it's just not
            # fed into chunking/embedding, satisfying "prevent low-quality
            # or corrupted content from silently entering the RAG index"
            # (the #1 non-negotiable requirement).
            raw_text = "\n".join(b.text for b in blocks) or None
            final_blocks = []

        return _PageExtraction(
            blocks=final_blocks,
            raw_text=raw_text,
            is_two_column=is_two_column,
            classification=assessment.classification,
            quality_status=assessment.status,
            quality_score=assessment.score,
            warnings=assessment.warnings,
            retry_count=assessment.retry_count,
            retry_reasons=assessment.retry_reasons,
            source_type=force_source_type or assessment.source_type,
            excluded_from_rag=excluded,
        )

    @staticmethod
    def _tag_chunk_quality(chunks: list[DocumentChunk], page_quality_map: dict[int, _PageExtraction]) -> None:
        """A chunk's `.page` is the page its first block started on (see
        semantic_chunker.py — unchanged by this feature, a chunk can
        already legitimately span a page boundary before this change)
        — used as the provenance key here, the same physical-page-keyed
        lookup pattern used throughout this module, so chunk-level
        quality metadata stays consistent with how every other
        per-page/per-chunk mapping in this parser works."""
        for chunk in chunks:
            extraction = page_quality_map.get(chunk.page)
            if extraction is None:
                continue
            chunk.quality_status = extraction.quality_status.value
            chunk.source_type = extraction.source_type.value
            chunk.page_classification = extraction.classification.value
            chunk.quality_score = extraction.quality_score

    @staticmethod
    def _extract_metadata(doc: "fitz.Document", document_id: str, page_languages: list[str | None]) -> DocumentMetadata:
        meta = doc.metadata or {}
        return DocumentMetadata(
            document_id=document_id,
            title=meta.get("title") or None,
            author=meta.get("author") or None,
            subject=meta.get("subject") or None,
            keywords=meta.get("keywords") or None,
            page_count=doc.page_count,
            language=detect_document_language(page_languages),
            creation_date=_pdf_date_to_iso(meta.get("creationDate")),
            modification_date=_pdf_date_to_iso(meta.get("modDate")),
        )

