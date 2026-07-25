from bussiness_logic.classification.services import ebti_precedent_local


def test_similar_cases_use_database_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        ebti_precedent_local,
        "LoadBtiCasesForCode",
        lambda _code: (
            {
                "bti_reference": "DE-1",
                "cn8": "19021990",
                "hs6": "190219",
                "assigned_code": "19021990",
                "issuing_country": "DE",
                "quality_status": "accepted",
                "bti_keyword_terms": "uncooked pasta not stuffed",
                "bti_case_summary_ko": "조리하지 않고 속을 채우지 않은 파스타",
            },
        ),
    )

    cases = ebti_precedent_local.FindSimilarCases(
        "19021990",
        "uncooked pasta not stuffed",
        limit=2,
    )

    assert len(cases) == 1
    assert "DE-1" in cases[0]["evidence_ref"]
    assert "공유 어휘" in cases[0]["similarity_comment"]
