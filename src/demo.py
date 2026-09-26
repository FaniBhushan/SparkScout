"""Deterministic synthetic model stub for an entirely offline UI demonstration."""

from __future__ import annotations

import json

from src.llm.client import ModelReply


def _prompt_json(prompt: str, label: str) -> object:
    start = prompt.index(label) + len(label)
    value, _ = json.JSONDecoder().raw_decode(prompt[start:].lstrip())
    return value


class OfflineDemoClient:
    """Exercise the real pipeline without claiming model-generated research quality."""

    async def complete(self, prompt: str, *, max_output_tokens: int) -> ModelReply:
        if "bounded web searches for ScoutSpark's Scout worker" in prompt:
            search = _prompt_json(prompt, "Resolved search configuration:\n")
            output = [self._query("scout-q-01", search)]
        elif "independent research landscape" in prompt:
            search = _prompt_json(prompt, "Resolved search configuration:\n")
            output = [self._query("library-q-01", search)]
        elif "idea-discovery worker" in prompt:
            sources = _prompt_json(prompt, "Source records:\n")
            source = sources[0]
            output = [{
                "candidate_id": "candidate-01",
                "title": "Evidence-grounded capstone prototype",
                "problem_statement": "Students need a scoped prototype backed by inspectable sources.",
                "target_users": ["Capstone students"],
                "proposed_outcome": "A small prototype and evaluation report",
                "why_it_matters": "The demo exercises source, retrieval, and citation checks.",
                "evidence": [{"source_id": source["source_id"]}],
            }]
        elif "evidence-based candidate assessor" in prompt:
            rubric = _prompt_json(prompt, "Evaluation configuration:\n")
            evidence = _prompt_json(prompt, "Retrieved evidence chunks:\n")
            reference = {
                "source_id": evidence[0]["source_id"],
                "chunk_id": evidence[0]["chunk_id"],
            }
            output = {
                "criteria": {
                    key: {"score": 3, "rationale": "Synthetic demo evidence only.", "evidence": [reference]}
                    for key in rubric["criteria"]
                },
                "hard_gates": {
                    key: {"passed": True, "rationale": "Demo path only.", "evidence": [reference]}
                    for key in rubric["hard_gates"]
                },
            }
        elif "draft one implementable capstone proposal" in prompt:
            evidence = _prompt_json(prompt, "Evidence chunks:\n")
            reference = {
                "source_id": evidence[0]["source_id"],
                "chunk_id": evidence[0]["chunk_id"],
            }
            output = {
                "gap_or_differentiation": "A synthetic demonstration; differentiation needs real research.",
                "scoped_mvp": ["Build a small prototype", "Document one evaluation"],
                "non_goals": ["Claim real-world validation"],
                "required_data": ["Permitted project data"],
                "required_tools": ["Python"],
                "access_assumptions": ["Verify access before implementation"],
                "technical_approach": "Implement and compare a simple baseline.",
                "alternatives": [{
                    "name": "Manual baseline", "description": "Evaluate manually first.",
                    "tradeoff": "Less automation, easier inspection.",
                }],
                "risks": ["Synthetic evidence cannot establish feasibility."],
                "unknowns": ["Real user need and data access"],
                "first_kill_test": "Check real data and user access before proceeding.",
                "evaluation_plan": {
                    "method": "Compare the prototype against a simple baseline.",
                    "objective_metrics": ["Task success rate"],
                    "success_criteria": ["Define a threshold before testing"],
                },
                "citations": [{
                    "claim": "The demo pipeline uses a captured fixture chunk.",
                    "references": [reference],
                }],
            }
        else:
            raise ValueError("offline demo does not support this prompt")
        return ModelReply(
            text=json.dumps(output), model="offline-demo",
            input_tokens=100, output_tokens=50,
        )

    @staticmethod
    def _query(query_id: str, search: dict) -> dict:
        provider = search["providers"][0]
        return {
            "query_id": query_id,
            "provider_id": provider["provider_id"],
            "text": "synthetic capstone fixture",
            "source_types": provider["source_types"],
            "content_types": provider["content_types"],
            "max_results": search["max_results_per_query"],
        }
