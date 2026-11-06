"""Run full en_core_web_sm, preserving every raw NER span."""
import argparse

if __package__:
    from .runner_common import (add_common_arguments, check_splits, load_ground_truth,
                                run_documents, seed_and_record_environment)
else:
    from runner_common import (add_common_arguments, check_splits, load_ground_truth,
                               run_documents, seed_and_record_environment)


def extract_spans(doc):
    return [{"label": ent.label_, "start": ent.start_char, "end": ent.end_char} for ent in doc.ents]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    args = parser.parse_args(argv)
    check_splits(args.splits)
    docs = load_ground_truth(args.ground_truth)
    seed_and_record_environment()
    import spacy
    nlp = spacy.load("en_core_web_sm")
    run_documents(docs, args.splits, args.raw_dir, args.output_dir, "spacy", nlp, extract_spans)


if __name__ == "__main__":
    main()
