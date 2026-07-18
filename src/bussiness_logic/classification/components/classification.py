"""Classification_Component — staged HS4 -> HS6 -> CN8 classifier."""
from __future__ import annotations

from bussiness_logic.pipeline.component_base import BasePipelineComponent
from bussiness_logic.classification.services.taric_branch_resolver import TaricBranchResolverTool
from bussiness_logic.pipeline.blackboard import BlackboardStore, now_iso
from bussiness_logic.utils.json_types import JsonObject


class ClassificationComponent(BasePipelineComponent):
    component_name = "Classification_Component"
    stage = "Classification"
    llm_model = "gemma4:26b"  # actual model selected by bridge.RuntimeAdapter

    def __init__(self) -> None:
        super().__init__()
        self._taric_resolver = TaricBranchResolverTool()

    def Run(self, store: BlackboardStore) -> None:
        bb = store.load()
        pes = bb.get("product_evidence_state") or {}
        if not pes:
            raise RuntimeError("No InputEvidenceState on the Blackboard.")
        self.ReadBlackBoard(pes["product_id"])
        routingContext = bb.get("routing_context")
        if isinstance(routingContext, dict):
            routingContextId = str(
                routingContext.get("routing_decision_id")
                or routingContext.get("routing_context_id")
                or ""
            )
            if routingContextId:
                self.ReadBlackBoard(routingContextId)
        else:
            routingContext = None

        if self._maybe_classify_staged(store, pes, routingContext, bb):
            return

        self._emit_unresolved(
            store,
            pes,
            why="staged_classifier_unavailable",
        )

    def _maybe_classify_staged(
        self,
        store: BlackboardStore,
        pes: dict,
        routingContext,
        bb: dict,
    ) -> bool:
        import os

        # Staged narrowing is the only runtime classification path. Legacy
        # Stage1 code remains in-tree as reference code, not as fallback.
        gate = (os.environ.get("ASAP_USE_STAGED_CLASSIFIER", "1") or "").strip().lower()
        if gate in ("0", "false", "no", "off"):
            self.reason("Staged classifier disabled by env; no legacy Stage1 fallback.")
            return False
        try:
            product_facts = bb.get("product_understanding") or {}
            if not product_facts:
                self.reason("Staged classifier: no product_understanding.")
                return False
            routing = routingContext if isinstance(routingContext, dict) else (
                bb.get("routing_context") or {}
            )

            from bussiness_logic.classification.services.staged_classification import StagedClassificationTool

            stagedTool = StagedClassificationTool()
            staged = stagedTool.classify(
                product_facts=product_facts,
                routing_context=routing,
            )
            stages = staged.get("stages") or []
            candidates = staged.get("candidates") or []
            if not staged.get("ok") or not candidates:
                self.reason(
                    "Staged classifier produced no candidates "
                    f"(error={staged.get('error') or 'no_candidates'})."
                )
                return False

            # Final validation (existing recommendation seam): closed-choice
            # veto over recorded recovery/reroute options. A fired override is
            # one more classify() pass inside the approved scope; a failed
            # second pass keeps the original result (deterministic guard).
            validatorRecord: dict | None = None
            validatorFlag = (os.environ.get("ASAP_STAGED_VALIDATOR", "1") or "").strip().lower()
            if validatorFlag in ("1", "true", "yes", "on"):
                verdict = stagedTool.validate_selection(
                    staged=staged,
                    product_facts=product_facts,
                    routing_context=routing,
                )
                if verdict.get("fired"):
                    validatorRecord = dict(verdict)
                if verdict.get("verdict") == "promote_candidate" and verdict.get("cn8"):
                    chosen = str(verdict["cn8"])
                    current_top = str((candidates[0] or {}).get("cn8") or "")
                    # 형제 재론 금지: 같은 hs4 안에서의 top1 교체는 staged가
                    # 증거(술어·결정·lexical)로 이미 내린 형제 비교를 LLM이
                    # 근거 없이 뒤집는 것 — 전 이력 489발화 실측에서 hs4 교차
                    # promote는 개악 0, 같은 hs4 내 promote는 hs6 순 -44
                    # (개악 77회 전원 190219→190230 단일 편향). keep으로 강등.
                    # ASAP_VALIDATOR_SIBLING_GUARD=0 으로 이전 동작 복귀.
                    sibling_guard = (os.environ.get(
                        "ASAP_VALIDATOR_SIBLING_GUARD", "1") or "1").strip() != "0"
                    if sibling_guard and chosen[:4] == current_top[:4] and chosen != current_top:
                        validatorRecord = {
                            **verdict,
                            "applied": False,
                            "blocked": "sibling_relitigation_guard",
                        }
                        self.reason(
                            f"Validator promote_candidate {chosen} blocked: same-hs4 "
                            f"sibling re-litigation (top={current_top})."
                        )
                        chosen = ""
                    reordered = sorted(
                        candidates,
                        key=lambda c: 0 if str(c.get("cn8") or "") == chosen else 1,
                    )
                    if str((reordered[0] or {}).get("cn8") or "") == chosen:
                        validatorRecord = {
                            **verdict,
                            "applied": True,
                            "original_top_cn8": str((candidates[0] or {}).get("cn8") or ""),
                        }
                        candidates = reordered
                        self.reason(
                            f"Validator promoted existing candidate {chosen}: "
                            f"{verdict.get('reason', '')[:120]}"
                        )
                scope = verdict.get("code") or verdict.get("chapter") or verdict.get("heading")
                if verdict.get("verdict") == "reroute" and scope:
                    # reroute = 라우터 의견 '복원' 전용: 대상 챕터가 라우터
                    # 자체 순위에서 staged 최종 챕터보다 높을 때만 허용.
                    # staged가 강해진 뒤 reroute는 구제 풀이 말라 개악만 남았다
                    # (최종 기준런 실측: 개악 3 — 쪽갈비 16→02, 떡볶이·산채
                    # 19→21 — vs 구제 1). validator가 제3의 챕터를 발명하는
                    # 것을 구조로 금지한다. ASAP_VALIDATOR_REROUTE_RESTORE_ONLY=0 복귀.
                    restore_only = (os.environ.get(
                        "ASAP_VALIDATOR_REROUTE_RESTORE_ONLY", "1") or "1").strip() != "0"
                    if restore_only:
                        order = [
                            str(d.get("chapter"))
                            for d in ((routing or {}).get("candidate_chapter_details") or [])
                            if isinstance(d, dict)
                        ]
                        target_ch = str(scope)[:2].zfill(2)
                        current_ch = str((candidates[0] or {}).get("cn8") or "")[:2]
                        t_rank = order.index(target_ch) if target_ch in order else 999
                        c_rank = order.index(current_ch) if current_ch in order else 999
                        if t_rank >= c_rank:
                            validatorRecord = {
                                **verdict,
                                "applied": False,
                                "blocked": "reroute_restore_only",
                            }
                            self.reason(
                                f"Validator reroute->{target_ch} blocked: not a router-"
                                f"restore (router rank {t_rank} vs current {c_rank})."
                            )
                            scope = None
                if verdict.get("verdict") in ("promote_recovery", "reroute", "narrow") and scope:
                    # [10회차-4] Validator 개입 권한 폐지 (VALIDATOR_DPO_
                    # DESIGN §1 — 설계자 확정): 재실행·후보 교체를 하지
                    # 않는다. G1/G2 교훈(무서명 개입 위험·observe 정당성)
                    # 의 Validator판 — 판단은 기록만 남기고, 독립 병렬
                    # 추리 대조군(DPO 수집)이 대체한다.
                    # '구validator 구제 손실' 정산 열: 폐지로 잃는 구제
                    # (종전 applied 케이스)를 정산에서 셀 수 있게 would_
                    # have_scope·verdict를 실물 보존.
                    scope = str(scope)
                    if len(scope) == 8:
                        scope = scope[:6]
                    validatorRecord = {
                        **verdict,
                        "applied": False,
                        "authority_revoked": True,
                        "would_have_scope": scope,
                        "original_top_cn8": str(
                            (candidates[0] or {}).get("cn8") or ""),
                    }
                    self.reason(
                        f"Validator authority revoked (observe-only): "
                        f"{verdict.get('verdict')} -> {scope} recorded, "
                        f"not applied."
                    )

            ccs_id = store.next_id("ccs")
            ccs_candidates: list[dict] = []
            classificationPaths = [
                path for path in (staged.get("paths") or []) if isinstance(path, dict)
            ]
            pathByCn8 = {
                str(path.get("cn8") or "")[:8]: path
                for path in classificationPaths
                if str(path.get("cn8") or "")[:8]
            }
            for candidate in candidates[:5]:
                cn8 = str(candidate.get("cn8") or "")[:8]
                if not cn8.isdigit() or len(cn8) != 8:
                    continue
                taric_branches = self._resolve_taric_branches(cn8)
                selected_branch = self._select_taric_branch(taric_branches)
                taric10 = selected_branch.get("taric10") or ""
                rank = len(ccs_candidates) + 1
                ccs_candidates.append({
                    "candidate_id": store.next_id("cand"),
                    "hs6": cn8[:6],
                    "cn8": cn8,
                    "hs8": cn8,  # 신 external 계열과 키 호환
                    "taric10": taric10,
                    "taric10_branch_candidates": taric_branches,
                    "taric10_resolution_mode": (
                        "enumerate_all_under_cn8" if taric_branches else "no_taric_branch_found"
                    ),
                    "taric10_is_recommended": False,
                    "taric10_branch_count": len(taric_branches),
                    "rank": rank,
                    "status": "proposed",
                    "candidate_source": "staged_classifier",
                    "llm_recommended": rank == 1,
                    "candidate_static_tree": self._staged_static_tree(
                        candidate,
                        pathByCn8.get(cn8),
                    ),
                    "hard_conditions": "",
                    "hard_condition_status": "not_applicable",
                    "hard_condition_evidence": [],
                    "classification_basis": [self._staged_basis(candidate)],
                    "supporting_product_facts": [],
                    "classification_evidence_refs": [],
                    # EBTI 판례는 표시 전용(원용도) — 선택·점수·검증 어디에도
                    # 관여하지 않는다 (판례의 코드 편향을 선택에 수입 금지).
                    "similar_ebti_cases": self._ebti_cases(cn8, product_facts),
                    "classification_citations": list(getattr(self, "_ontology_reads", []) or []),
                    "required_facts": [],
                    "unknowns": [],
                })

            if not ccs_candidates:
                self.reason("Staged classifier produced no valid CN8.")
                return False
            selectedCn8 = str((ccs_candidates[0] or {}).get("cn8") or "")[:8]
            selectedPath = pathByCn8.get(selectedCn8) or (
                classificationPaths[0] if classificationPaths else {}
            )

            store.append("candidate_code_sets", {
                "object_type": "CandidateCodeSet",
                "created_by": self.component_name,
                "created_at": now_iso(),
                "candidate_set_id": ccs_id,
                "product_id": pes["product_id"],
                "classification_trace": {
                    "mode": "staged_narrowing",
                    "stages": stages,
                    "validator": validatorRecord,
                    "backtracking_recommended": bool(
                        validatorRecord and validatorRecord.get("applied")
                    ),
                },
                "classification_paths": classificationPaths,
                "recovery_candidates": staged.get("recovery_candidates") or [],
                "route_disagreements": staged.get("route_disagreements") or [],
                # [8회차-0] 개입 서명 의무화 — G1/G2·병합 게이트·BTI 소환의
                # 관측/발동 기록을 blackboard에 영속화. ON 모드가 무서명으로
                # 개입한 6런 A/B 사고(22캐시 기록 0)의 처방: staged 결과에는
                # 있었으나 이 지점이 싣지 않아 유실됐다. validator 재실행
                # (rerun) 경로도 staged 교체 후 동일 키를 읽으므로 함께 남는다.
                "router_trust_gate": staged.get("router_trust_gate") or [],
                "merge_gate_observations": staged.get("merge_gate_observations") or [],
                "bti_summons": staged.get("bti_summons") or [],
                "selected_path": selectedPath,
                "candidates": ccs_candidates,
            })
            self.WriteBlackBoard(ccs_id)
            for c in ccs_candidates:
                self.WriteBlackBoard(c["candidate_id"])
            self.reason(
                f"Staged narrowing emitted {len(ccs_candidates)} candidate(s) "
                f"(hs4->hs6->cn8, {len(stages)} stages)."
            )
            return True
        except Exception as exc:  # noqa: BLE001 — component emits unresolved instead
            self.reason(f"Staged classifier error ({exc!r}).")
            return False


    def _staged_static_tree(
        self,
        candidate: dict,
        classificationPath: dict | None = None,
    ) -> dict:
        levelScoresValue = (
            classificationPath.get("level_scores")
            if isinstance(classificationPath, dict)
            else {}
        )
        levelScores = levelScoresValue if isinstance(levelScoresValue, dict) else {}
        candidateScore = self._read_float(candidate.get("score"), fallback=0.0)
        nodes: list[dict] = []
        for level, label in (("hs4", "HS4"), ("hs6", "HS6"), ("cn8", "CN8")):
            code = str(candidate.get(level) or "").strip()
            if not code:
                continue
            nodes.append({
                "level": level,
                "label": label,
                "code": code,
                "description": str(candidate.get("description") or "") if level == "cn8" else "",
                "score": self._read_float(
                    levelScores.get(level),
                    fallback=candidateScore if level == "cn8" else 0.0,
                ),
                "matched_keywords": [],
            })
        return {
            "total_score": candidateScore,
            "level_scores": {
                level: self._read_float(levelScores.get(level), fallback=0.0)
                for level in ("hs4", "hs6", "cn8")
                if level in levelScores
            },
            "retrieval_sources": ["staged_narrowing"],
            "nodes": nodes,
        }

    @staticmethod
    def _read_float(value: object, *, fallback: float) -> float:
        if isinstance(value, bool):
            return fallback
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _ebti_cases(cn8: str, product_facts: dict) -> list[dict]:
        """유사 EBTI 판례 (표시 전용) — 실패는 빈 목록, 파이프라인 무영향."""
        try:
            from bussiness_logic.classification.services.ebti_precedent_local import FindSimilarCases

            ih = product_facts.get("identity_hints") or {}
            identity_text = " ".join(
                str(part) for part in (
                    ih.get("normalized_tariff_description") or "",
                    ih.get("translated_product_name") or "",
                    " ".join(ih.get("identity_terms") or []),
                    ih.get("ingredient_class") or "",
                ) if part
            )
            return FindSimilarCases(cn8, identity_text, limit=2)
        except Exception:  # noqa: BLE001 — 근거 표시 실패가 분류를 깨면 안 된다
            return []

    def _staged_basis(self, candidate: dict) -> str:
        desc = str(candidate.get("description") or "")[:160]
        verdict = str(candidate.get("quantitative_verdict") or "")
        base = f"Staged narrowing hs4->hs6->cn8 selected CN8={candidate.get('cn8')}: {desc}"
        if verdict and verdict != "neutral":
            base += f" [%-gate: {verdict}]"
        return base[:600]


    def _resolve_taric_branches(self, cn8: str) -> list[JsonObject]:
        if not cn8 or cn8 == "99999999":
            return []
        try:
            branches = self._taric_resolver.resolve(
                cn8,
                only_declarable_leaf=False,
                only_kr_applicable=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.reason(f"TaricBranchResolverTool error for CN8={cn8}: {exc}")
            return []

        out = [b.to_dict() for b in branches]
        if out:
            self.CreateCiteSource(
                "taric_master_table",
                f"cn8={cn8}",
                snippet=f"{len(out)} TARIC10 branch candidate(s)",
                reason="TaricBranchResolverTool branch retrieval.",
            )
        return out

    # ------------------------------------------------------------------ helpers
    def _select_taric_branch(self, branches: list[JsonObject]) -> JsonObject:
        """Pick a compatibility primary TARIC10 from deterministic branches.

        This is not a legal recommendation. The full branch list remains on
        the candidate and Document_Component packages every branch. The primary
        value only preserves older UI/API paths that expect cand["taric10"].
        """
        if not branches:
            return {}

        def score(branch: JsonObject) -> tuple[int, int, int, int, int]:
            description = (branch.get("branch_description") or "").strip().lower()
            return (
                1 if branch.get("applies_to_origin_kr") else 0,
                1 if branch.get("is_declarable_leaf") else 0,
                0 if branch.get("needs_review") else 1,
                int(branch.get("measure_row_count") or 0),
                1 if description == "other" else 0,
            )

        selected = max(branches, key=score)
        out = dict(selected)
        out["selection_reason"] = (
            "Compatibility primary only, not a TARIC10 recommendation. "
            "All TARIC master branches under this CN8 are retained in "
            "taric10_branch_candidates; this primary prefers KR-applicable "
            "declarable leaves, then non-review branches, then measure coverage."
        )
        return out
    def _emit_unresolved(
        self,
        store: BlackboardStore,
        pes: dict,
        *,
        why: str,
        debug: JsonObject | None = None,
    ) -> None:
        ccs_id = store.next_id("ccs")
        candidateCodeSet = {
            "object_type": "ClassificationCandidateSet",
            "created_by": self.component_name,
            "created_at": now_iso(),
            "candidate_set_id": ccs_id,
            "product_id": pes["product_id"],
            "classification_status": "needs_more_facts",
            "failure_reason": why,
            "shortlisted_candidates": list(self._ontology_reads),
            "candidates": [],
        }
        if debug:
            candidateCodeSet["resolver_debug"] = debug
        store.append("candidate_code_sets", candidateCodeSet)
        self.WriteBlackBoard(ccs_id)
        self.reason(
            f"Classification unresolved ({why}); wrote empty ClassificationCandidateSet "
            "instead of a synthetic 99999999 candidate."
        )
