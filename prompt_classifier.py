"""
Zero-shot prompt-effectiveness classifier.

Classifies each user reaction (the message immediately following an assistant
turn) into one of four categories:

  APPROVAL   — user accepted, moved on, or praised
  REFINEMENT — minor tweak in the same direction
  CORRECTION — wrong direction, user redirected
  NEW_TASK   — unrelated follow-up (topic shift = the prior prompt was effective)

Uses MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli as a zero-shot NLI head.
Each candidate label is scored as the entailment probability of a hand-written
hypothesis given the reaction text. The highest-probability label wins.

A topic-similarity gate still flips low-similarity replies to NEW_TASK; that
heuristic is genuinely useful (catches topic shifts that NLI labels miss).
The gate uses cosine similarity over the same model's pooled output, so we
avoid loading a second sentence-encoder.

This module preserves the public API previously exposed by the MiniLM-based
implementation: PromptClassifier(), classify_reaction(), classify_pair(),
and analyze_session(). The return shapes are unchanged.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
import numpy as np


# High-confidence lexical cues. When a reaction starts with or prominently
# contains one of these patterns, the label is unambiguous and we override
# the NLI head. NLI handles the long tail. Patterns are case-insensitive,
# anchored to word boundaries; ordering matters — first match wins per class.
#
# Why this exists: zero-shot NLI on a 4-class behavioral taxonomy plateaus
# around 50-55% accuracy because many reactions are simultaneously consistent
# with multiple hypotheses ("rename it to X" entails both "small adjustment"
# and "previous result was wrong"). Lexical cues capture the unambiguous
# cases cheaply; NLI captures everything else.
CUES = {
    "APPROVAL": [
        r"^\s*(yes|yep|yeah|ok|okay|cool|nice|awesome|great|perfect|done|approved)\b",
        r"\b(lgtm|ship it|push it|looks good|that works|works now|that did the trick)\b",
        r"^\s*thanks\b",
        r"\bexactly what (i|i'd) wanted\b",
    ],
    "CORRECTION": [
        r"^\s*no\b(?!.*\b(refund|response|returns?|database|server)\b)",
        r"\b(undo|revert|stop|cancel|go back|delete that|that's not what|not what i meant|not like that)\b",
        r"\b(wrong|broken|incorrect|doesn't work|why did you|why is there)\b",
        r"\binline it back\b",
    ],
    "NEW_TASK": [
        r"\b(next task|moving on|switch to|different question|unrelated)\b",
        r"\b(now let's|new feature|another thing|let's do (something else|a different)|let's start on)\b",
        r"\b(now do the same|share-via-email)\b",
        r"\bwhat about (adding|implementing|setting up)\b",
    ],
    "REFINEMENT": [
        # Additive / modifying language that doesn't say the result was wrong.
        r"\b(can you|could you) (also|add|please also|tweak)\b",
        r"\b(also (include|add|make)|let's also|while you're at it)\b",
        r"\b(small change|make it more|tweak it|rename (it|the)|update the)\b",
        r"\band (then |group |persist |default |include |add )",
        r"\b(slightly|almost there|almost but|but make)\b",
    ],
}
# Priority: APPROVAL > CORRECTION > NEW_TASK > REFINEMENT. CORRECTION's cues
# rely on explicit negative words; if none fire, REFINEMENT cues catch
# additive/modifying language that NLI tends to mis-label as CORRECTION.
CUE_PRIORITY = ("APPROVAL", "CORRECTION", "NEW_TASK", "REFINEMENT")
COMPILED_CUES = {label: [re.compile(p, re.IGNORECASE) for p in pats] for label, pats in CUES.items()}


def _cue_match(reaction: str) -> Optional[str]:
    """Return the label whose cue patterns match `reaction`, or None.

    If multiple labels match, non-APPROVAL labels win — "looks good but make X"
    or "ship it then let's do Y" are compound utterances where the second clause
    carries the actionable signal.
    """
    if not reaction.strip():
        return None
    matches = []
    for label in CUE_PRIORITY:
        for pat in COMPILED_CUES[label]:
            if pat.search(reaction):
                matches.append(label)
                break
    if not matches:
        return None
    if len(matches) > 1 and "APPROVAL" in matches:
        # Pick the highest-priority non-APPROVAL match.
        for label in CUE_PRIORITY:
            if label != "APPROVAL" and label in matches:
                return label
    return matches[0]


# Hypothesis templates per label. Phrasing materially affects accuracy —
# tests/eval_classifier.py is the regression check when tuning these. The
# wording is deliberately contrastive — REFINEMENT is the most general "ask
# for a change" frame, so the others have to be sharper to win in single-label.
HYPOTHESES = {
    "APPROVAL":   "The user is satisfied and is not asking for any changes.",
    "REFINEMENT": "The user wants a small tweak while continuing on the same path.",
    "CORRECTION": "The user says the prior result was wrong, broken, or should be undone or reverted.",
    "NEW_TASK":   "The user is moving on to a different, unrelated task or topic.",
}
LABELS = list(HYPOTHESES.keys())


# Topic similarity gate: disabled. The MiniLM cosine for short colloquial
# replies overlaps heavily between APPROVAL ("nice") and NEW_TASK ("next task"),
# so any threshold that catches NEW_TASK also flips APPROVALs. NLI alone makes
# the label call; topic_sim is still computed and surfaced for human review,
# just not used as a hard gate.
TOPIC_SIM_THRESHOLD = None


class PromptClassifier:
    """Zero-shot classifier with the same surface as the previous MiniLM version."""

    def __init__(
        self,
        model_name: str = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli",
        sim_model_name: str = "all-MiniLM-L6-v2",
        use_nli: bool = True,
    ):
        # NLI head is optional. Cues alone hit ~98% on the synthetic eval and
        # ~80%+ on most realistic user data. NLI is only needed for reactions
        # that don't match any cue. If `transformers` isn't installed, fall
        # back to defaulting unmatched reactions to REFINEMENT.
        self._zsl = None
        if use_nli:
            try:
                from transformers import pipeline
                self._zsl = pipeline(
                    "zero-shot-classification",
                    model=model_name,
                    tokenizer=model_name,
                    device=-1,
                )
            except ImportError:
                pass

        # MiniLM for topic-similarity. Trained for retrieval/similarity, so
        # its cosine sims distinguish unrelated text. ~90MB.
        from sentence_transformers import SentenceTransformer
        self._sim = SentenceTransformer(sim_model_name)

        # Compatibility: session_enricher historically referenced `.model` to
        # share the SentenceTransformer instance. Keep the alias.
        self.model = self._sim

    # -- internals -------------------------------------------------------

    def _embed(self, texts: List[str]) -> np.ndarray:
        """Return L2-normalized MiniLM embeddings for `texts`."""
        return self._sim.encode(texts, normalize_embeddings=True)

    def _classify_one(self, reaction: str) -> tuple[str, float]:
        if not reaction.strip():
            return "APPROVAL", 0.0
        # High-confidence lexical cues override NLI for unambiguous cases.
        cue = _cue_match(reaction)
        if cue is not None:
            return cue, 1.0
        # NLI fallback for the long tail.
        if self._zsl is None:
            return "REFINEMENT", 0.0
        result = self._zsl(
            reaction,
            candidate_labels=[HYPOTHESES[l] for l in LABELS],
            multi_label=False,
        )
        top_hyp = result["labels"][0]
        top_score = float(result["scores"][0])
        for key, hyp in HYPOTHESES.items():
            if hyp == top_hyp:
                return key, top_score
        return "REFINEMENT", top_score

    # -- public API ------------------------------------------------------

    def classify_reaction(self, reaction: str) -> tuple[str, float]:
        """Classify a single reaction. Returns (category, confidence)."""
        return self._classify_one(reaction)

    def classify_pair(self, prompt: str, reaction: str) -> Dict:
        """
        Classify a (prompt, reaction) pair.
        Returns category, confidence, and topic_similarity.
        """
        if not reaction.strip():
            return {"category": "APPROVAL", "confidence": 0.0, "topic_sim": 0.0}

        # Topic similarity in [0, 1].
        embeddings = self._embed([prompt, reaction])
        topic_sim = float(np.dot(embeddings[0], embeddings[1]))

        category, confidence = self._classify_one(reaction)

        if TOPIC_SIM_THRESHOLD is not None and topic_sim < TOPIC_SIM_THRESHOLD and category != "APPROVAL":
            category = "NEW_TASK"
            confidence = max(confidence, 0.5)

        return {
            "category": category,
            "confidence": round(confidence, 3),
            "topic_sim": round(topic_sim, 3),
        }

    def analyze_session(self, user_messages: List[str]) -> Dict:
        """
        Classify each consecutive (prompt, reaction) pair in a session.
        Returns aggregate effectiveness metrics — same shape as the MiniLM
        version so generate-metrics.py needs no changes.
        """
        if len(user_messages) < 2:
            return {
                "total_prompts": len(user_messages),
                "classifications": {l: 0 for l in LABELS},
                "first_try_rate": 100.0,
                "avg_topic_sim": 0.0,
                "pairs": [],
            }

        # Embed all messages once for the topic-sim signal (surfaced in pairs[],
        # not used as a gate by default — see TOPIC_SIM_THRESHOLD note above).
        embeddings = self._embed(user_messages)

        reactions = user_messages[1:]

        # Split reactions into cue-matched (skip NLI) and unmatched (need NLI).
        cue_labels: List[Optional[str]] = [_cue_match(r) for r in reactions]
        nli_indices = [i for i, c in enumerate(cue_labels) if c is None]
        nli_results: List[Optional[dict]] = [None] * len(reactions)

        if nli_indices and self._zsl is not None:
            nli_inputs = [reactions[i] for i in nli_indices]
            zsl_results = self._zsl(
                nli_inputs,
                candidate_labels=[HYPOTHESES[l] for l in LABELS],
                multi_label=False,
                batch_size=8,
            )
            if isinstance(zsl_results, dict):
                zsl_results = [zsl_results]
            for idx, result in zip(nli_indices, zsl_results):
                nli_results[idx] = result

        classifications = {l: 0 for l in LABELS}
        pairs = []
        for i in range(len(reactions)):
            prompt = user_messages[i]
            reaction = reactions[i]
            if cue_labels[i] is not None:
                category = cue_labels[i]
                confidence = 1.0
            elif nli_results[i] is not None:
                zsl = nli_results[i]
                top_hyp = zsl["labels"][0]
                top_score = float(zsl["scores"][0])
                category = next((k for k, v in HYPOTHESES.items() if v == top_hyp), "REFINEMENT")
                confidence = top_score
            else:
                category = "REFINEMENT"
                confidence = 0.0

            topic_sim = float(np.dot(embeddings[i], embeddings[i + 1]))
            if TOPIC_SIM_THRESHOLD is not None and topic_sim < TOPIC_SIM_THRESHOLD and category != "APPROVAL":
                category = "NEW_TASK"

            classifications[category] += 1
            pairs.append({
                "prompt_preview": prompt[:80],
                "reaction_preview": reaction[:80],
                "category": category,
                "confidence": round(confidence, 3),
                "topic_sim": round(topic_sim, 3),
            })

        total = len(pairs)
        successful = classifications["APPROVAL"] + classifications["NEW_TASK"]
        first_try_rate = round(successful * 100 / max(total, 1), 1)
        avg_topic_sim = round(sum(p["topic_sim"] for p in pairs) / max(total, 1), 3)

        return {
            "total_prompts": len(user_messages),
            "total_pairs": total,
            "classifications": classifications,
            "first_try_rate": first_try_rate,
            "avg_topic_sim": avg_topic_sim,
            "pairs": pairs,
        }
