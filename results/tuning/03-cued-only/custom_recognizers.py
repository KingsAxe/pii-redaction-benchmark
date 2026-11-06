"""The only tunable configuration; changes must be logged using dev only."""
from presidio_analyzer import Pattern, PatternRecognizer
from presidio_analyzer.context_aware_enhancers import LemmaContextAwareEnhancer

ID_REGEX = (r"(?im)(?<=(?:\bBVN(?:\s+No)?|\bNIN(?:\s+No)?|Bank Verification Number|"
            r"National ID Number)\s*[:\-]\s*)\b[1-9]\d{10}\b")
ID_BASE_SCORE = 0.05
CONTEXT_BOOST = 0.35
MIN_CONTEXT_SCORE = 0.4
BVN_CONTEXT = ["bvn", "bvn no", "bank verification", "bank verification number", "verification number"]
NIN_CONTEXT = ["nin", "nin no", "national id", "national id number", "national identity",
               "national identification", "identity number"]


def configure_custom(analyzer):
    analyzer.context_aware_enhancer = LemmaContextAwareEnhancer(
        context_similarity_factor=CONTEXT_BOOST,
        min_score_with_context_similarity=MIN_CONTEXT_SCORE)
    for name, context in (("BVN", BVN_CONTEXT), ("NIN", NIN_CONTEXT)):
        analyzer.registry.add_recognizer(PatternRecognizer(
            supported_entity="ID", name=f"{name}PatternRecognizer",
            patterns=[Pattern(name=f"{name}_pattern", regex=ID_REGEX, score=ID_BASE_SCORE)],
            context=context))
