"""Run the full pipeline on PDF files from the command line.

Usage:
  python scripts/analyze.py umowa.pdf aneks.pdf protokol.pdf --out wynik.json [--letter wezwanie.docx]
  python scripts/analyze.py ... --show-anonymized   # print anonymized text and stop (nothing is sent)

Requires ANTHROPIC_API_KEY (or another credential source of the Anthropic SDK).
Use only public sample agreements unless running on the law firm's server.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.letter import LetterParties, build_letter  # noqa: E402
from pipeline.llm import AnthropicClient  # noqa: E402
from pipeline.ner import configured_detectors  # noqa: E402
from pipeline.ocr import ocr_page, tesseract_available  # noqa: E402
from pipeline.run import analysis_to_dict, analyze_case, prepare_case  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("analysis.json"))
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--letter", type=Path, help="also write a draft demand letter (.docx)")
    parser.add_argument("--capped", action="store_true", help="demand the amount after the contractual cap")
    parser.add_argument("--show-anonymized", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    case_id = uuid.uuid4().hex[:12]
    ocr = ocr_page if tesseract_available() else None
    if ocr is None:
        logging.getLogger("claims").warning("tesseract with 'pol' not found: scanned pages will be empty")

    prepared = prepare_case(case_id, args.pdfs, ocr=ocr, detectors=configured_detectors())
    if args.show_anonymized:
        for doc in prepared.anonymized:
            for i, page in enumerate(doc.pages, start=1):
                print(f"===== {doc.id} ({doc.filename}) page {i} =====\n{page}\n")
        return 0

    client = AnthropicClient()
    analysis = analyze_case(client, prepared, args.as_of)
    args.out.write_text(
        json.dumps(analysis_to_dict(analysis, prepared.mapping), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"written {args.out}")

    if args.letter:
        result = build_letter(client, case_id, analysis.extraction.extraction, analysis.calculation,
                              LetterParties(), args.letter, capped=args.capped, letter_date=dt.date.today())
        print(f"written {result.path}")
        for w in result.warnings:
            print(f"  ! {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
