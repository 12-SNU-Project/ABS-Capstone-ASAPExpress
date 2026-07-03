"""
Evidence_Intake_Component — stub.

Reads raw user input (product name, description, optional OCR text, source
URLs) and writes a InputEvidenceState onto the Blackboard.

This stub does *not* call an LLM. A real implementation would parse OCR
output, extract composition tables, and normalize ingredient terms.
"""
from __future__ import annotations


from agents.component_base import BasePipelineComponent
from agents.blackboard import BlackboardStore, now_iso
from bussiness_logic.utils.json_types import JsonObject


class EvidenceIntakeComponent(BasePipelineComponent):
    component_name = "Evidence_Intake_Component"
    stage = "Product_Intake"
    llm_model = None  # deterministic intake; flip to a model when OCR/LLM is wired

    def __init__(self, raw_input: JsonObject):
        super().__init__()
        self.raw_input = raw_input

    def Run(self, store: BlackboardStore) -> None:
        prod_id = store.next_id("prod")
        obs = {
            "product_name": self.raw_input.get("product_name", ""),
            "description": self.raw_input.get("description", ""),
            "composition": self.raw_input.get("composition", []),
            "reconstructed_product_facts": self.raw_input.get(
                "reconstructed_product_facts",
                [],
            ),
            "unresolved_product_facts": self.raw_input.get(
                "unresolved_product_facts",
                [],
            ),
            "product_fact_conflicts": self.raw_input.get(
                "product_fact_conflicts",
                [],
            ),
            "reconstructed_fact_texts": self.raw_input.get(
                "reconstructed_fact_texts",
                [],
            ),
            "input_reconstruction": self.raw_input.get("input_reconstruction", {}),
            "ocr_text": self.raw_input.get("ocr_text", []),
            "source_urls": self.raw_input.get("source_urls", []),
            "origin_country": self.raw_input.get("origin_country", "KR"),
            "intended_use": self.raw_input.get("intended_use", "unknown"),
            "warnings": self.raw_input.get("warnings", []),
        }

        # Stub-level inferred facts: a single proposed principal_form when the
        # name string hints at one. A production component would do much more.
        inferred: list[JsonObject] = []
        name = (obs["product_name"] or "").lower()
        for kw, form in [("noodle", "pasta_dry"), ("ramen", "pasta_dry"),
                         ("라면", "pasta_dry"), ("cream", "cosmetic_cream"),
                         ("lotion", "cosmetic_lotion")]:
            if kw in name:
                inferred.append({
                    "fact_key": "principal_form",
                    "value": form,
                    "confidence": 0.5,
                    "evidence": [],
                    "status": "proposed",
                })
                self.reason(f"Detected token '{kw}' in product_name; proposed principal_form={form}.")
                break

        pes = {
            "object_type": "InputEvidenceState",
            "created_by": self.component_name,
            "created_at": now_iso(),
            "product_id": prod_id,
            "observed_facts": obs,
            "inferred_facts": inferred,
            "unknowns": ["composition_pct" if not obs["composition"] else "",
                         "intended_use" if obs["intended_use"] == "unknown" else ""],
            "evidence_pointers": [],
        }
        pes["unknowns"] = [u for u in pes["unknowns"] if u]
        store.put("product_evidence_state", pes)
        self.WriteBlackBoard(prod_id)
        self.reason(f"Created InputEvidenceState {prod_id} from raw input.")
