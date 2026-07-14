"""Compatibility aliases for moved classification/product/document helpers."""

from __future__ import annotations

import importlib
import sys

_ALIASES = {
    "branch_decision_evaluator": "bussiness_logic.classification.rules.branch_decision_evaluator",
    "branch_index_repository": "bussiness_logic.classification.repositories.branch_index_repository",
    "branch_predicate_evaluator": "bussiness_logic.classification.rules.branch_predicate_evaluator",
    "chapter_index_client": "bussiness_logic.classification.repositories.chapter_index_client",
    "chapter_index_repository": "bussiness_logic.classification.repositories.chapter_index_repository",
    "domain_router": "bussiness_logic.document.services.domain_router",
    "ebti_precedent_local": "bussiness_logic.classification.services.ebti_precedent_local",
    "encyclopedia_lookup": "bussiness_logic.product.services.encyclopedia_lookup",
    "identity_distiller": "bussiness_logic.product.services.identity_distiller",
    "pre_classification_router": "bussiness_logic.classification.services.pre_classification_router",
    "staged_classification": "bussiness_logic.classification.services.staged_classification",
    "taric_branch_resolver": "bussiness_logic.classification.services.taric_branch_resolver",
}

for oldName, newName in _ALIASES.items():
    sys.modules[__name__ + "." + oldName] = importlib.import_module(newName)
