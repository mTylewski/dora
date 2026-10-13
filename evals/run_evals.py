"""Evaluation runner (CLAUDE.md, section 10).

  python evals/run_evals.py                      # all cases in evals/expected/, real API calls
  python evals/run_evals.py --only umowa_a       # one case
  python evals/run_evals.py --reuse              # rescore cached runs without calling the API
  python evals/run_evals.py --anonymization      # offline PII-leak gate only
  python evals/run_evals.py --update-baseline    # accept the current report as the new baseline

Exit code 1 when a threshold fails, a field regresses against the baseline,
or any personal value leaks through anonymization. Run after every change of a prompt,
the schema or a model. Uses only public sample agreements (evals/contracts/).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.scoring import check_thresholds, regressions, score_case, summarize  # noqa: E402
from pipeline.anonymize import anonymize_pages, find_leaks  # noqa: E402

EVALS = ROOT / "evals"
CONTRACTS = EVALS / "contracts"
EXPECTED = EVALS / "expected"
RUNS = EVALS / "runs"
REPORTS = EVALS / "reports"


def run_key(expected: dict, files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    for prompt in sorted((ROOT / "prompts").glob("*.md")):
        h.update(prompt.read_bytes())
    for cfg in ("models.yaml", "calculator.yaml"):
        h.update((ROOT / "config" / cfg).read_bytes())
    h.update(str(expected.get("as_of")).encode())
    return h.hexdigest()[:16]


def run_case(name: str, expected: dict, reuse: bool) -> dict:
    files = [CONTRACTS / f for f in expected["documents"]]
    cache = RUNS / f"{name}-{run_key(expected, files)}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    if reuse:
        raise FileNotFoundError(f"no cached run for {name} (run without --reuse)")

    from pipeline.llm import AnthropicClient
    from pipeline.ocr import ocr_page, tesseract_available
    from pipeline.run import analyze_case, prepare_case

    started = time.monotonic()
    prepared = prepare_case(f"eval-{name}", files, ocr=ocr_page if tesseract_available() else None)
    as_of = dt.date.fromisoformat(str(expected.get("as_of", dt.date.today())))
    analysis = analyze_case(AnthropicClient(), prepared, as_of)
    seconds = time.monotonic() - started
    result = {
        "extraction": analysis.extraction.extraction.model_dump(mode="json"),
        "issues": [{"path": i.path, "issue": i.issue.value} for i in analysis.extraction.issues],
        "clause_ids": [f.clause_id for f in analysis.clauses.flags],
        "penalties_grosze": [p.uncapped_grosze for p in analysis.calculation.result.penalties]
        if analysis.calculation.result else None,
        "seconds": seconds,
        "timings_ms": analysis.timings_ms,
    }
    RUNS.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def anonymization_gate() -> list[str]:
    """Synthetic texts with known personal values; any value left in the output is a leak."""
    path = EVALS / "anonymization" / "cases.yaml"
    leaks = []
    for case in yaml.safe_load(path.read_text(encoding="utf-8")):
        pages, _ = anonymize_pages({"d": [case["text"]]})
        for value in find_leaks(pages["d"][0], case["secrets"]):
            leaks.append(f"{case['name']}: {value}")
    return leaks


def write_report(summary: dict, failures: list[str], regress: list[str], leaks: list[str]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {"at": stamp, "summary": summary, "failures": failures, "regressions": regress, "leaks": leaks}
    (REPORTS / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# Raport ewaluacji {stamp}", ""]
    for key, value in summary.items():
        if key in ("per_field", "failed_fields"):
            continue
        lines.append(f"- **{key}**: {value if not isinstance(value, float) else f'{value:.3f}'}")
    lines += ["", "## Trafność per pole", ""]
    lines += [f"- {f}: {v:.3f}" for f, v in summary.get("per_field", {}).items()]
    for title, items in (("Progi niespełnione", failures), ("Regresje", regress), ("Przecieki PII", leaks),
                         ("Błędne pola", summary.get("failed_fields", []))):
        if items:
            lines += ["", f"## {title}", ""] + [f"- {i}" for i in items]
    path = REPORTS / "latest.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only")
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--anonymization", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()

    leaks = anonymization_gate()
    if args.anonymization:
        print("Anonimizacja: 0 przecieków" if not leaks else "PRZECIEKI:\n" + "\n".join(leaks))
        return 1 if leaks else 0

    scores = []
    for exp_path in sorted(EXPECTED.glob("*.yaml")):
        name = exp_path.stem
        if args.only and name != args.only:
            continue
        expected = yaml.safe_load(exp_path.read_text(encoding="utf-8"))
        result = run_case(name, expected, args.reuse)
        scores.append(score_case(name, expected, result["extraction"], result["issues"], result["clause_ids"],
                                 result["seconds"], result.get("penalties_grosze")))
        print(f"{name}: {sum(scores[-1].field_hits.values())}/{len(scores[-1].field_hits)} pól, "
              f"{result['seconds']:.0f} s")

    if not scores:
        print("Brak przypadków w evals/expected/ — zobacz evals/README.md")
        return 1 if leaks else 0

    summary = summarize(scores)
    baseline_path = REPORTS / "baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["summary"] if baseline_path.exists() else None
    failures = check_thresholds(summary)
    regress = [] if args.only else regressions(summary, baseline)
    report = write_report(summary, failures, regress, leaks)
    print(f"Raport: {report}")
    if args.update_baseline:
        baseline_path.write_text((REPORTS / "latest.json").read_text(encoding="utf-8"), encoding="utf-8")
        print("Zapisano nowy baseline.")
    for title, items in (("Progi", failures), ("Regresje", regress), ("Przecieki PII", leaks)):
        for i in items:
            print(f"  ! {title}: {i}")
    return 1 if (failures or regress or leaks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
