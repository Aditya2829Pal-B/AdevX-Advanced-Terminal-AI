"""Reflection, self-critique, confidence scoring, and hallucination detection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from adevx.core.autonomy_models import ExecutionNode, ReflectionReport, ReviewAction


@dataclass(slots=True)
class ReflectionEngine:
    confidence_threshold: float = 0.58
    hallucination_threshold: float = 0.45

    def review(self, node: ExecutionNode, output: str) -> ReflectionReport:
        confidence = self._confidence(output)
        hallucination_risk = self._hallucination_risk(output)
        issues: list[str] = []
        strengths: list[str] = []
        action = ReviewAction.ACCEPT
        revised_payload: dict[str, str] = {}

        if len(output.strip()) < 12:
            issues.append("Output is too short and likely incomplete.")
        else:
            strengths.append("Output has non-trivial content length.")

        if "not sure" in output.lower() or "maybe" in output.lower():
            issues.append("Hedged language detected.")

        if hallucination_risk >= self.hallucination_threshold:
            issues.append("Potential hallucination markers found.")

        if confidence < self.confidence_threshold:
            issues.append("Confidence below threshold.")

        if issues and node.attempts < node.max_attempts:
            action = ReviewAction.RETRY
            revised_payload = {
                "reflection_hint": "Increase verification, cite concrete evidence, and avoid uncertain claims.",
            }
        elif issues and node.attempts >= node.max_attempts:
            if hallucination_risk >= self.hallucination_threshold:
                action = ReviewAction.REPLAN
            else:
                action = ReviewAction.HALT
        elif not issues:
            strengths.append("Confidence and hallucination checks passed.")

        return ReflectionReport(
            node_id=node.node_id,
            confidence=confidence,
            hallucination_risk=hallucination_risk,
            issues=issues,
            strengths=strengths,
            action=action,
            revised_payload=revised_payload,
            notes="Automated reflection pass completed.",
        )

    @staticmethod
    def _confidence(output: str) -> float:
        text = output.strip()
        score = 0.35
        if len(text) > 60:
            score += 0.15
        if any(token in text.lower() for token in ("because", "therefore", "step", "result", "verified")):
            score += 0.18
        if re.search(r"\b(error|failed|unknown)\b", text.lower()):
            score -= 0.1
        if "```" in text:
            score += 0.12
        return max(0.0, min(score, 0.99))

    @staticmethod
    def _hallucination_risk(output: str) -> float:
        text = output.lower()
        risk = 0.1
        if "as everyone knows" in text:
            risk += 0.2
        if "definitely true" in text or "guaranteed" in text:
            risk += 0.2
        if "source:" not in text and "http" not in text and len(text) > 200:
            risk += 0.12
        if "i cannot verify" in text:
            risk += 0.08
        return max(0.0, min(risk, 0.99))
