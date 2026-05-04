"""
Embedding-based prompt effectiveness classifier.
Uses all-MiniLM-L6-v2 to classify user reactions into:
  APPROVAL  — user accepted, moved on, or praised
  REFINEMENT — minor tweak requested, same direction
  CORRECTION — wrong direction, user redirected
  NEW_TASK   — unrelated follow-up (topic shift = prompt was effective)

Approach:
  1. Embed reference phrases for each category
  2. For each (prompt, reaction) pair:
     a. Embed the reaction
     b. Cosine sim to each category's reference centroid
     c. Also compute prompt↔reaction similarity (high = same topic)
     d. Assign category
"""
import numpy as np
from typing import List, Tuple, Dict

# Reference phrases per category — used to build centroids
REFERENCE_PHRASES = {
    "APPROVAL": [
        "looks good", "lgtm", "perfect", "great", "nice", "thanks",
        "yes that works", "ship it", "push it", "commit",
        "exactly what I wanted", "approved", "good job", "done",
        "yes", "ok", "cool", "awesome", "love it",
    ],
    "REFINEMENT": [
        "can you also add", "one more thing", "small change",
        "make it more", "adjust the", "what about adding",
        "could you tweak", "slightly different", "almost but",
        "also include", "and then", "let's also", "update the copy",
        "change the color", "move this to", "rename it to",
    ],
    "CORRECTION": [
        "no not that", "wrong", "that's not what I meant",
        "don't do that", "stop", "undo", "revert", "why did you",
        "I said", "actually I want", "remove that", "that's incorrect",
        "no something else", "pointless", "unnecessary", "why is there",
        "this is broken", "this doesn't work", "go back",
        "cancel", "delete that", "not like that",
    ],
    "NEW_TASK": [
        "now let's work on", "next task", "switch to",
        "moving on", "different question", "unrelated but",
        "can you help with", "new feature", "another thing",
        "let's do", "what about", "how do I",
    ],
}


class PromptClassifier:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)
        self.centroids = self._build_centroids()

    def _build_centroids(self) -> Dict[str, np.ndarray]:
        """Pre-compute category centroids from reference phrases."""
        centroids = {}
        for category, phrases in REFERENCE_PHRASES.items():
            embeddings = self.model.encode(phrases, normalize_embeddings=True)
            centroids[category] = np.mean(embeddings, axis=0)
            # Re-normalize the centroid
            centroids[category] /= np.linalg.norm(centroids[category])
        return centroids

    def classify_reaction(self, reaction: str) -> Tuple[str, float]:
        """Classify a single reaction text. Returns (category, confidence)."""
        if not reaction.strip():
            return "APPROVAL", 0.0

        emb = self.model.encode([reaction], normalize_embeddings=True)[0]

        scores = {}
        for category, centroid in self.centroids.items():
            scores[category] = float(np.dot(emb, centroid))

        best = max(scores, key=scores.get)
        confidence = scores[best]
        return best, confidence

    def classify_pair(self, prompt: str, reaction: str) -> Dict:
        """
        Classify a (prompt, reaction) pair.
        Returns category, confidence, and topic_similarity.
        """
        if not reaction.strip():
            return {"category": "APPROVAL", "confidence": 0.0, "topic_sim": 0.0}

        embeddings = self.model.encode(
            [prompt, reaction], normalize_embeddings=True
        )
        topic_sim = float(np.dot(embeddings[0], embeddings[1]))

        # Classify the reaction
        category, confidence = self.classify_reaction(reaction)

        # Heuristic boost: if topic similarity is very low, likely NEW_TASK
        if topic_sim < 0.15 and category != "APPROVAL":
            category = "NEW_TASK"
            confidence = max(confidence, 0.5)

        return {
            "category": category,
            "confidence": round(confidence, 3),
            "topic_sim": round(topic_sim, 3),
        }

    def analyze_session(self, user_messages: List[str]) -> Dict:
        """
        Analyze a sequence of user messages from a session.
        Returns aggregate effectiveness metrics.
        """
        if len(user_messages) < 2:
            return {
                "total_prompts": len(user_messages),
                "classifications": {"APPROVAL": 0, "REFINEMENT": 0, "CORRECTION": 0, "NEW_TASK": 0},
                "first_try_rate": 100.0,
                "avg_topic_sim": 0.0,
                "pairs": [],
            }

        # Batch embed all messages at once (much faster than one-by-one)
        all_embeddings = self.model.encode(user_messages, normalize_embeddings=True)

        classifications = {"APPROVAL": 0, "REFINEMENT": 0, "CORRECTION": 0, "NEW_TASK": 0}
        pairs = []

        for i in range(len(user_messages) - 1):
            prompt = user_messages[i]
            reaction = user_messages[i + 1]

            topic_sim = float(np.dot(all_embeddings[i], all_embeddings[i + 1]))

            # Classify reaction against centroids
            reaction_emb = all_embeddings[i + 1]
            scores = {cat: float(np.dot(reaction_emb, c)) for cat, c in self.centroids.items()}
            category = max(scores, key=scores.get)
            confidence = scores[category]

            if topic_sim < 0.15 and category != "APPROVAL":
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
        avg_topic_sim = round(
            sum(p["topic_sim"] for p in pairs) / max(len(pairs), 1), 3
        )

        return {
            "total_prompts": len(user_messages),
            "total_pairs": total,
            "classifications": classifications,
            "first_try_rate": first_try_rate,
            "avg_topic_sim": avg_topic_sim,
            "pairs": pairs,
        }
