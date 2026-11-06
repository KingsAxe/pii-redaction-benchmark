"""Run default, additive NG phone, or custom Presidio with en_core_web_sm."""
import argparse

if __package__:
    from .runner_common import (add_common_arguments, check_splits, load_ground_truth,
                                require_custom_freeze, run_documents, seed_and_record_environment)
else:
    from runner_common import (add_common_arguments, check_splits, load_ground_truth,
                               require_custom_freeze, run_documents, seed_and_record_environment)


def build_analyzer(config):
    import tldextract
    # EmailRecognizer uses this public callable. Pin its bundled suffix snapshot
    # rather than fetching external data or using a machine-dependent cache.
    tldextract.extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_analyzer.predefined_recognizers import PhoneRecognizer
    if config not in ("default", "ng_phone", "custom"):
        raise ValueError("Unknown Presidio configuration")
    engine = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
    }).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=engine, supported_languages=["en"])
    if config in ("ng_phone", "custom"):
        analyzer.registry.add_recognizer(PhoneRecognizer(
            supported_regions=["NG"], name="NigeriaPhoneRecognizer"))
    if config == "custom":
        if __package__:
            from .custom_recognizers import configure_custom
        else:
            from custom_recognizers import configure_custom
        configure_custom(analyzer)
    return analyzer


def extract_spans(results):
    return [{"label": r.entity_type, "start": r.start, "end": r.end} for r in results]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=("default", "ng_phone", "custom"), default="default")
    add_common_arguments(parser)
    args = parser.parse_args(argv)
    check_splits(args.splits)
    if args.config == "custom" and "test" in args.splits:
        require_custom_freeze()
    docs = load_ground_truth(args.ground_truth)
    seed_and_record_environment()
    analyzer = build_analyzer(args.config)
    run_documents(docs, args.splits, args.raw_dir, args.output_dir,
                  f"presidio_{args.config}",
                  lambda text: analyzer.analyze(text=text, language="en"), extract_spans)


if __name__ == "__main__":
    main()
