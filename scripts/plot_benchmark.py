"""Render a two-panel comparison directly from the existing results CSV."""
import csv
import math

from PIL import Image, ImageDraw

if __package__:
    from .evaluate import CONFIGS
    from .figure_common import INK, ROOT, font, save_figure, verify_evidence
else:
    from evaluate import CONFIGS
    from figure_common import INK, ROOT, font, save_figure, verify_evidence

NAMES = ("spaCy", "Presidio default", "Presidio + NG phone", "Presidio custom generic", "Presidio custom")
COLORS = ("#0072B2", "#009E73", "#E69F00", "#CC79A7", "#D55E00")


def load_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_config = {row["config"]: row for row in rows}
    if len(rows) != len(CONFIGS) or set(by_config) != set(CONFIGS):
        raise ValueError("Expected exactly the five established configurations")
    ordered = [by_config[config] for config in CONFIGS]
    for row in ordered:
        if row["split"] != "test":
            raise ValueError("Comparison must use test results")
        for metric in ("leak_rate", "over_redaction_rate"):
            value = float(row[metric])
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Invalid percentage in CSV")
    if len({row["documents"] for row in ordered}) != 1:
        raise ValueError("Document counts differ between configurations")
    return ordered


def main():
    verify_evidence()
    source = ROOT / "results/results.csv"
    rows = load_rows(source)
    image = Image.new("RGB", (2400, 1450), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 70), "Local PII redaction benchmark", font=font(68, "bold"), fill=INK)
    draw.text((80, 173), f"{rows[0]['documents']} synthetic test documents | Nigerian-format business text | en_core_web_sm",
              font=font(35), fill=INK)
    panels = [("leak_rate", 620, 690, 10, ("PII character", "leak rate")),
              ("over_redaction_rate", 1640, 560, 2, ("Non-PII character", "over-redaction rate"))]
    scales = {}
    for metric, left, width, step, title in panels:
        values = [100 * float(row[metric]) for row in rows]
        maximum = max(step, math.ceil(max(values) * 1.1 / step) * step)
        scales[metric] = {"minimum_percent": 0, "maximum_percent": maximum}
        draw.text((left, 285), title[0], font=font(44, "bold"), fill=INK)
        draw.text((left, 340), title[1], font=font(44, "bold"), fill=INK)
        draw.text((left, 408), f"Lower is better | 0-{maximum}% scale", font=font(30), fill=INK)
        for tick in range(0, maximum + 1, step):
            x = left + width * tick / maximum
            draw.line((x, 490, x, 1130), fill="#E1E5E9", width=2)
            draw.text((x, 1150), f"{tick}%", font=font(28), fill=INK, anchor="mt")
        draw.line((left, 490, left, 1130), fill="#65717D", width=3)
        for index, value in enumerate(values):
            y = 535 + index * 130
            end = left + width * value / maximum
            if value > 0:
                draw.rectangle((left, y - 31, end, y + 31), fill=COLORS[index])
            draw.text((end + 18, y), f"{value:.2f}%", font=font(34, "bold"), fill=INK, anchor="lm")
    for index, name in enumerate(NAMES):
        draw.text((80, 535 + index * 130), name, font=font(35), fill=INK, anchor="lm")
    notes = ["Panels use different percentage scales; both axes start at zero.",
             "Both custom variants have identical values for these two measures.",
             "Custom's leading-zero exclusion depends on the synthetic generator.",
             "Source: results/results.csv | No inference or new benchmark measurements."]
    for index, note in enumerate(notes):
        draw.text((80, 1230 + index * 44), note, font=font(30), fill=INK)
    save_figure(image, "benchmark_comparison.png", "benchmark_comparison",
                [source, ROOT / "scripts/plot_benchmark.py", ROOT / "scripts/figure_common.py",
                 ROOT / "scripts/evaluate.py", ROOT / "results/reporting_integrity.json"],
                ".\\venv\\Scripts\\python.exe scripts/plot_benchmark.py",
                configuration_order=list(CONFIGS), panel_scales=scales,
                percentages={row["config"]: {metric: 100 * float(row[metric])
                             for metric in ("leak_rate", "over_redaction_rate")} for row in rows})


if __name__ == "__main__":
    main()
