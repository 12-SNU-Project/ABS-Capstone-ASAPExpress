from bussiness_logic.classification.rules.question_contract import (
    ApplyClassificationAnswers,
    BuildClassificationQuestionKey,
)


def _detail(value: str = '["egg"]', op: str = "contains") -> dict:
    return {
        "cond": "material_composition",
        "op": op,
        "verdict": "silent",
        "field": "composition_facts.ingredient_classes",
        "value": value,
        "why": "field_empty",
    }


def test_question_key_is_stable_and_scope_sensitive() -> None:
    common = {
        "stage": "hs6",
        "parentCode": "1902",
        "candidateCode": "190211",
        "axis": "material_composition",
        "canonicalField": "composition_facts.ingredient_classes",
        "conditionValue": '["egg"]',
        "predicateOp": "contains",
    }
    first = BuildClassificationQuestionKey(**common)
    assert first == BuildClassificationQuestionKey(**common)
    assert first != BuildClassificationQuestionKey(
        **{**common, "candidateCode": "190219"}
    )


def test_yes_answer_confirms_exact_question() -> None:
    detail = _detail()
    key = BuildClassificationQuestionKey(
        stage="hs6",
        parentCode="1902",
        candidateCode="190211",
        axis="material_composition",
        canonicalField="composition_facts.ingredient_classes",
        conditionValue='["egg"]',
        predicateOp="contains",
    )
    status, details, keys = ApplyClassificationAnswers(
        decisionStatus="undecided",
        decisionDetail=[detail],
        productFacts={
            "_classification_answer_facts": [{
                "question_key": key,
                "answer": "yes",
                "answer_id": "qa_001",
                "answered_at": "2026-07-24T00:00:00+09:00",
            }]
        },
        stage="hs6",
        parentCode="1902",
        candidateCode="190211",
    )
    assert status == "confirmed"
    assert keys == [key]
    assert details[-1]["op"] == "user_answer"
    assert details[-1]["verdict"] == "true"


def test_answer_cannot_leak_to_sibling() -> None:
    key = BuildClassificationQuestionKey(
        stage="hs6",
        parentCode="1902",
        candidateCode="190211",
        axis="material_composition",
        canonicalField="composition_facts.ingredient_classes",
        conditionValue='["egg"]',
        predicateOp="contains",
    )
    status, details, keys = ApplyClassificationAnswers(
        decisionStatus="undecided",
        decisionDetail=[_detail()],
        productFacts={
            "_classification_answer_facts": [{
                "question_key": key,
                "answer": "yes",
            }]
        },
        stage="hs6",
        parentCode="1902",
        candidateCode="190219",
    )
    assert status == "undecided"
    assert keys == []
    assert all(item.get("op") != "user_answer" for item in details)


def test_unknown_answer_remains_silence() -> None:
    detail = _detail()
    key = BuildClassificationQuestionKey(
        stage="hs6",
        parentCode="1902",
        candidateCode="190211",
        axis="material_composition",
        canonicalField="composition_facts.ingredient_classes",
        conditionValue='["egg"]',
        predicateOp="contains",
    )
    status, details, keys = ApplyClassificationAnswers(
        decisionStatus="undecided",
        decisionDetail=[detail],
        productFacts={
            "_classification_answer_facts": [{
                "question_key": key,
                "answer": "unknown",
            }]
        },
        stage="hs6",
        parentCode="1902",
        candidateCode="190211",
    )
    assert status == "undecided"
    assert keys == [key]
    assert details[-1]["verdict"] == "silent"


def test_question_key_distinguishes_predicate_polarity() -> None:
    common = {
        "stage": "hs6",
        "parentCode": "1902",
        "candidateCode": "190211",
        "axis": "material_composition",
        "canonicalField": "composition_facts.ingredient_classes",
        "conditionValue": '["egg"]',
    }
    assert BuildClassificationQuestionKey(
        **common,
        predicateOp="contains",
    ) != BuildClassificationQuestionKey(
        **common,
        predicateOp="not_contains",
    )


def test_yes_to_positive_question_violates_not_contains_predicate() -> None:
    detail = _detail(op="not_contains")
    key = BuildClassificationQuestionKey(
        stage="hs6",
        parentCode="1902",
        candidateCode="190211",
        axis="material_composition",
        canonicalField="composition_facts.ingredient_classes",
        conditionValue='["egg"]',
        predicateOp="not_contains",
    )
    status, details, keys = ApplyClassificationAnswers(
        decisionStatus="undecided",
        decisionDetail=[detail],
        productFacts={
            "_classification_answer_facts": [{
                "question_key": key,
                "answer": "yes",
            }]
        },
        stage="hs6",
        parentCode="1902",
        candidateCode="190211",
    )
    assert status == "violated"
    assert keys == [key]
    assert details[-1]["verdict"] == "false"


def test_no_to_positive_question_confirms_not_contains_predicate() -> None:
    detail = _detail(op="not_contains")
    key = BuildClassificationQuestionKey(
        stage="hs6",
        parentCode="1902",
        candidateCode="190211",
        axis="material_composition",
        canonicalField="composition_facts.ingredient_classes",
        conditionValue='["egg"]',
        predicateOp="not_contains",
    )
    status, details, _ = ApplyClassificationAnswers(
        decisionStatus="undecided",
        decisionDetail=[detail],
        productFacts={
            "_classification_answer_facts": [{
                "question_key": key,
                "answer": "no",
            }]
        },
        stage="hs6",
        parentCode="1902",
        candidateCode="190211",
    )
    assert status == "confirmed"
    assert details[-1]["verdict"] == "true"


def _confirmed(code: str) -> dict:
    return {
        "code": code,
        "decision": "confirmed",
        "descr": "Named branch",
        "residual": False,
    }


def test_multiple_o_uses_scoped_bti_for_gri3_code_confirmation() -> None:
    from bussiness_logic.classification.services import staged_classification as sc

    previous = sc._BTI_RECALL_CACHE
    sc._BTI_RECALL_CACHE = {
        "cases": [
            {
                "ref": "BTI-1",
                "cn8": "19022099",
                "toks": ["stuffed", "dumpling"],
                "phrases": ["stuffed dumpling"],
            },
            {
                "ref": "BTI-2",
                "cn8": "19022099",
                "toks": ["stuffed", "dumpling"],
                "phrases": ["stuffed dumpling"],
            },
        ],
        "df": {"stuffed": 2, "dumpling": 2},
        "n_docs": 2,
        "avg_len": 2.0,
    }
    try:
        ranked = [_confirmed("1902"), _confirmed("2104")]
        losers = sc._ApplyGri3(
            ranked,
            {
                "identity_hints": {
                    "normalized_tariff_description": "stuffed dumpling"
                }
            },
        )
    finally:
        sc._BTI_RECALL_CACHE = previous
    assert ranked[0]["code"] == "1902"
    assert ranked[0]["gri3"] == "gri3_precedent"
    assert ranked[0]["gri_bti"]["authority"] == "code_confirmation"
    assert losers == ["2104"]


def test_multiple_o_uses_scoped_bti_for_gri6_code_confirmation() -> None:
    from bussiness_logic.classification.services import staged_classification as sc

    previous = sc._BTI_RECALL_CACHE
    sc._BTI_RECALL_CACHE = {
        "cases": [
            {
                "ref": "BTI-1",
                "cn8": "19021990",
                "toks": ["wheat", "noodle"],
                "phrases": ["wheat noodle"],
            },
            {
                "ref": "BTI-2",
                "cn8": "19021990",
                "toks": ["wheat", "noodle"],
                "phrases": ["wheat noodle"],
            },
        ],
        "df": {"wheat": 2, "noodle": 2},
        "n_docs": 2,
        "avg_len": 2.0,
    }
    try:
        ranked = [_confirmed("190211"), _confirmed("190219")]
        losers = sc._ApplyGri6(
            ranked,
            {
                "identity_hints": {
                    "normalized_tariff_description": "wheat noodle"
                }
            },
            prefix_len=6,
        )
    finally:
        sc._BTI_RECALL_CACHE = previous
    assert ranked[0]["code"] == "190219"
    assert ranked[0]["gri3"] == "gri6_precedent"
    assert losers == ["190211"]
