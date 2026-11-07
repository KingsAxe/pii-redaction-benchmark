"""Illustrate character unions from existing synthetic test text and predictions."""
import argparse
import json
from collections import Counter

from PIL import Image, ImageDraw

if __package__:
    from .evaluate import CONFIGS
    from .figure_common import INK, ROOT, font, save_figure, verify_evidence
    from .metrics import DEFAULT_PRED_LABEL_MAP
    from .runner_common import document_id, load_doc_text, load_ground_truth
else:
    from evaluate import CONFIGS
    from figure_common import INK, ROOT, font, save_figure, verify_evidence
    from metrics import DEFAULT_PRED_LABEL_MAP
    from runner_common import document_id, load_doc_text, load_ground_truth

CATEGORIES = ("masked_pii", "missed_pii", "over_redacted", "other")


def coverage(text, entities, predictions):
    def positions(spans):
        result = set()
        for span in spans:
            if type(span["start"]) is not int or type(span["end"]) is not int or not 0 <= span["start"] < span["end"] <= len(text):
                raise ValueError("Span outside document bounds")
            result.update(range(span["start"], span["end"]))
        return result
    pii = positions(entities)
    predicted = positions([p for p in predictions if p["label"] in DEFAULT_PRED_LABEL_MAP])
    sets = {"masked_pii": pii & predicted, "missed_pii": pii - predicted,
            "over_redacted": predicted - pii, "other": set(range(len(text))) - (pii | predicted)}
    masked = "".join("#" if i in predicted and char != "\n" else char for i, char in enumerate(text))
    assert len(masked) == len(text)
    assert [i for i, c in enumerate(masked) if c == "\n"] == [i for i, c in enumerate(text) if c == "\n"]
    return sets, masked


def wrapped_positions(text, columns=58):
    """Wrap the original once; return original offsets, retaining every space."""
    rows, start = [], 0
    for line in text.split("\n"):
        remaining = line
        if not remaining:
            rows.append((start, []))
        while remaining:
            cut = min(columns, len(remaining))
            if len(remaining) > columns:
                space = remaining.rfind(" ", 0, columns)
                if space > 0:
                    cut = space + 1
            rows.append((start, list(range(start, start + cut))))
            start += cut
            remaining = remaining[cut:]
        start += 1  # source newline; never inserted into a wrapped row
    flattened = [i for _, row in rows for i in row]
    assert flattened == [i for i, char in enumerate(text) if char != "\n"]
    return rows


def select_document(docs, requested=None):
    candidates = sorted((doc for doc in docs if doc["split"] == "test"), key=document_id)
    if not candidates:
        raise ValueError("No test documents")
    if requested is None:
        return candidates[0], "First test document in lexicographic document-ID order; no performance search"
    for doc in candidates:
        if document_id(doc) == requested:
            return doc, "Explicit document ID supplied with --doc-id; no performance search by renderer"
    raise ValueError("Requested document ID is not in the test split")


def render(text, entities, spans, doc_id, config):
    sets, masked = coverage(text, entities, spans)
    rows = wrapped_positions(text)
    image = Image.new("RGB", (2600, 460 + len(rows) * 50 + 330), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 65), "Predicted span coverage: one synthetic example", font=font(56, "bold"), fill=INK)
    draw.text((80, 155), f"Document ID: {doc_id}", font=font(34), fill=INK)
    draw.text((80, 207), f"Configuration: {config}", font=font(34), fill=INK)
    draw.text((80, 266), "Synthetic example; selected by document ID, not performance.", font=font(33), fill=INK)
    draw.text((80, 355), "Original with ground-truth PII", font=font(40, "bold"), fill=INK)
    draw.text((1340, 355), "Mapped prediction coverage", font=font(40, "bold"), fill=INK)
    mono = font(30, "mono")
    cell_width = draw.textlength("M", font=mono)
    rendered = Counter({kind: 0 for kind in CATEGORIES})
    for row_number, (start, indices) in enumerate(rows):
        y = 450 + row_number * 50
        for left in (80, 1340):
            draw.text((left, y + 2), f"{start:04d}", font=font(24, "mono"), fill="#65717D")
        for column, index in enumerate(indices):
            category = next(kind for kind in CATEGORIES if index in sets[kind])
            rendered[category] += 1
            original_x = 180 + column * cell_width
            masked_x = 1440 + column * cell_width
            if index in sets["masked_pii"] or index in sets["missed_pii"]:
                draw.rectangle((original_x, y - 3, original_x + cell_width, y + 38), fill="#E5F0FA")
                draw.line((original_x, y + 38, original_x + cell_width, y + 38), fill="#0072B2", width=3)
            draw.text((original_x, y), text[index], font=mono, fill=INK, anchor="la")
            foreground = INK
            if category == "masked_pii":
                draw.rectangle((masked_x, y - 3, masked_x + cell_width, y + 38), fill="#244A64")
                foreground = "white"
            elif category == "missed_pii":
                draw.rectangle((masked_x, y - 3, masked_x + cell_width, y + 38), fill="#FFF0E9")
                for offset in (34, 39):
                    draw.line((masked_x, y + offset, masked_x + cell_width, y + offset), fill="#A33C00", width=2)
            elif category == "over_redacted":
                draw.rectangle((masked_x, y - 3, masked_x + cell_width, y + 38), fill="#FFE2B6")
                draw.line((masked_x, y + 30, masked_x + cell_width, y + 8), fill="#B0772C", width=2)
            draw.text((masked_x, y), masked[index], font=mono, fill=foreground, anchor="la")
    # Newlines retain structure instead of becoming glyphs; account for them explicitly.
    line_break_counts = {kind: sum(text[i] == "\n" for i in positions) for kind, positions in sets.items()}
    for kind in CATEGORIES:
        assert rendered[kind] + line_break_counts[kind] == len(sets[kind])
    y = 460 + len(rows) * 50
    notes = ["Legend: original underlining = ground-truth PII; gutter numbers = original character offsets.",
             "Masked view: dark # = covered PII; double-underlined text = missed PII; hatched # = covered non-PII.",
             f"Example-only character counts: PII covered {len(sets['masked_pii'])} | PII missed {len(sets['missed_pii'])} | non-PII covered {len(sets['over_redacted'])}",
             f"Wrapping retains source offsets. Mapped line breaks are preserved and counted: {sum(line_break_counts[kind] for kind in ('masked_pii', 'over_redacted'))}. Unmapped labels are ignored.",
             "Illustration of predicted span coverage; not a production redaction tool."]
    for index, note in enumerate(notes):
        draw.text((80, y + 30 + index * 53), note, font=font(30), fill=INK)
    return image, {"character_counts": {kind: len(positions) for kind, positions in sets.items()},
                   "rendered_character_counts": dict(rendered), "preserved_line_break_counts": line_break_counts,
                   "wrap_columns": 58, "mask_character": "#", "newlines_preserved": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc-id")
    parser.add_argument("--config", choices=CONFIGS, default="presidio_custom")
    args = parser.parse_args(argv)
    verify_evidence()
    doc, rule = select_document(load_ground_truth(), args.doc_id)
    text = load_doc_text(doc)
    path = ROOT / "data/predictions" / f"{args.config}__test.json"
    predictions = json.loads(path.read_text(encoding="utf-8"))[document_id(doc)]["spans"]
    image, counts = render(text, doc["entities"], predictions, document_id(doc), args.config)
    command = f'.\\venv\\Scripts\\python.exe scripts/render_document_example.py --config {args.config}'
    if args.doc_id is not None:
        command += " --doc-id '" + args.doc_id.replace("'", "''") + "'"
    save_figure(image, "document_example.png", "document_example",
                [ROOT / "data/ground_truth.json", ROOT / doc["file"], path,
                 ROOT / "results/freeze.json", ROOT / "scripts/metrics.py",
                 ROOT / "scripts/runner_common.py", ROOT / "scripts/render_document_example.py",
                 ROOT / "scripts/figure_common.py", ROOT / "scripts/evaluate.py"], command,
                selected_document=document_id(doc), configuration=args.config, selection_rule=rule,
                coverage_policy="Union of all mapped prediction spans, independent of assignment and label correctness",
                **counts)
    print(json.dumps({"document": document_id(doc), "config": args.config, "selection": rule, **counts}, indent=2))


if __name__ == "__main__":
    main()
