"""Write the retrieval+screening composition report from stored artifacts."""

from __future__ import annotations

import json

from benchmarks.retrieval.composition import (
    COMPOSED_JSON_PATH,
    COMPOSED_MARKDOWN_PATH,
    compose_from_disk,
    render_markdown,
)


def main() -> None:
    """Recompute the composed gate and overwrite the committed report files."""
    report = compose_from_disk()
    COMPOSED_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMPOSED_JSON_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    COMPOSED_MARKDOWN_PATH.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "reduction_rate": report["reduction_rate"],
                "cost_reduction": report["cost_reduction"],
                "good_recall": report["good_recall"],
                "fitting_recall": report["fitting_recall"],
                "n_assessed": report["n_assessed"],
                "composed_usd": report["composed_usd"],
                "assess_all_usd": report["assess_all_usd"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
