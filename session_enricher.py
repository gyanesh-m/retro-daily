"""
Session enrichment via MiniLM embeddings.
Classifies sessions by topic, interaction type, and extracts representative summaries.
Shares the SentenceTransformer model instance from PromptClassifier to avoid double loading.

Self-correcting: sessions that don't match any known topic are classified as "new" and
accumulated. When enough "new" entries cluster together, a candidate topic label is proposed
for human/LLM confirmation and added to custom-topics.json for future runs.
"""
import json
import os
import numpy as np
from datetime import date
from typing import List, Tuple, Dict, Optional
from pathlib import Path


DATA_DIR = Path(os.environ.get("CLAUDE_DAILY_DATA") or (Path.home() / ".claude" / "metrics"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
METRICS_DIR = DATA_DIR  # backwards-compat alias
CUSTOM_TOPICS_FILE = DATA_DIR / "custom-topics.json"
NEW_TOPICS_FILE = DATA_DIR / "new-topics.json"

# Confidence threshold: below this, classify as "new" (needs categorization)
NEW_TOPIC_THRESHOLD = 0.18
# Minimum "new" entries before attempting to derive a category
NEW_TOPIC_CLUSTER_MIN = 3
# Similarity threshold for clustering "new" entries together
NEW_CLUSTER_SIM_THRESHOLD = 0.35

# Built-in topic labels — descriptive phrases for embedding discrimination
BUILTIN_TOPIC_LABELS = {
    "swift_ios": "Swift iOS macOS Apple mobile app development Xcode SwiftUI UIKit AppKit",
    "web_frontend": "JavaScript TypeScript React Vue frontend web HTML CSS Next.js design",
    "python": "Python scripting data processing backend Django Flask pip",
    "golang": "Golang Go backend server microservices concurrency",
    "rust": "Rust systems programming performance memory safety cargo",
    "devops": "DevOps CI CD pipeline deployment Docker Kubernetes infrastructure",
    "testing": "Testing TDD unit tests integration tests test coverage vitest jest",
    "debugging": "Debugging fixing errors troubleshooting crash logs stacktrace",
    "ml_ai": "Machine learning AI model training inference MLX fine-tuning",
    "web_scraping": "Web scraping data extraction automation browser crawling",
    "git_workflow": "Git version control branching merging pull request code review",
    "documentation": "Documentation README writing explaining comments docs",
    "ui_design": "UI UX design layout styling responsive animation polish",
    "api_backend": "API backend REST GraphQL server endpoints database SQL",
    "configuration": "Configuration setup environment settings install deploy config",
    "auth_security": "Authentication security OAuth login permissions encryption",
}

INTERACTION_TYPE_LABELS = {
    "feature_build": "The user is asking to build or create a new feature or component from scratch",
    "bug_fix": "The user is reporting a bug or error and asking for it to be fixed or debugged",
    "refactor": "The user wants code to be cleaned up restructured or optimized without changing behavior",
    "exploration": "The user is exploring the codebase or asking how things work or reading code",
    "configuration": "The user is setting up environment configuring tools deploying or installing",
    "testing": "The user wants tests written or test coverage improved or test failures investigated",
    "documentation": "The user wants documentation or explanations or README files written",
    "code_review": "The user wants code reviewed for quality best practices or correctness",
}


def load_custom_topics() -> Dict[str, str]:
    """Load user-confirmed custom topic labels from disk."""
    if CUSTOM_TOPICS_FILE.exists():
        try:
            with open(CUSTOM_TOPICS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_custom_topics(topics: Dict[str, str]):
    """Save custom topic labels to disk."""
    with open(CUSTOM_TOPICS_FILE, "w") as f:
        json.dump(topics, f, indent=2)


def load_new_topics() -> List[Dict]:
    """Load accumulated uncategorized 'new' session entries."""
    if NEW_TOPICS_FILE.exists():
        try:
            with open(NEW_TOPICS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_new_topics(entries: List[Dict]):
    """Save uncategorized entries. Keep last 50 to avoid unbounded growth."""
    with open(NEW_TOPICS_FILE, "w") as f:
        json.dump(entries[-50:], f, indent=2)


class SessionEnricher:
    def __init__(self, model):
        """Takes a SentenceTransformer model instance (shared with PromptClassifier)."""
        self.model = model

        # Merge built-in + custom topics
        self._custom_topics = load_custom_topics()
        all_topics = {**BUILTIN_TOPIC_LABELS, **self._custom_topics}
        self._topic_embeddings = self._build_label_embeddings(all_topics)
        self._interaction_embeddings = self._build_label_embeddings(INTERACTION_TYPE_LABELS)

        # Track "new" entries accumulated this run for batch save
        self._new_entries_buffer = []

    def _build_label_embeddings(self, labels: Dict[str, str]) -> Dict[str, np.ndarray]:
        """Pre-compute normalized embeddings for label descriptions."""
        keys = list(labels.keys())
        texts = list(labels.values())
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return {k: emb for k, emb in zip(keys, embeddings)}

    def classify_topics(self, user_messages: List[str]) -> List[Tuple[str, float]]:
        """
        Classify session topics. If best score is below NEW_TOPIC_THRESHOLD,
        classifies as "new" and stores the session for future categorization.
        Returns list of (topic, score) tuples sorted by score, max 5.
        """
        if not user_messages:
            return []

        combined = " ".join(msg[:200] for msg in user_messages[:20])
        if not combined.strip():
            return []

        emb = self.model.encode([combined], normalize_embeddings=True)[0]

        scores = []
        for label, label_emb in self._topic_embeddings.items():
            sim = float(np.dot(emb, label_emb))
            scores.append((label, round(sim, 3)))

        scores.sort(key=lambda x: x[1], reverse=True)
        best_score = scores[0][1] if scores else 0

        if best_score < NEW_TOPIC_THRESHOLD:
            # None of the known topics match well — classify as "new"
            summary_msgs = [m[:150] for m in user_messages if len(m.strip()) > 10][:5]
            self._new_entries_buffer.append({
                "date": date.today().isoformat(),
                "best_match": scores[0][0] if scores else None,
                "best_score": best_score,
                "sample_messages": summary_msgs,
                "embedding": emb.tolist(),  # store for clustering
            })
            return [("new", best_score)]

        # Return known topics above threshold
        matched = [(t, s) for t, s in scores if s > 0.12]
        return matched[:5]

    def classify_interaction_type(self, user_messages: List[str]) -> str:
        """Classify the dominant interaction type of a session."""
        if not user_messages:
            return "exploration"

        combined = " ".join(msg[:200] for msg in user_messages[:20])
        if not combined.strip():
            return "exploration"

        emb = self.model.encode([combined], normalize_embeddings=True)[0]

        best_type = "exploration"
        best_score = -1.0
        for label, label_emb in self._interaction_embeddings.items():
            sim = float(np.dot(emb, label_emb))
            if sim > best_score:
                best_score = sim
                best_type = label

        return best_type

    def extractive_summary(self, user_messages: List[str], top_k: int = 3) -> List[str]:
        """Select top_k most representative user messages by embedding similarity to centroid."""
        meaningful = [m for m in user_messages if len(m.strip()) > 15]
        if not meaningful:
            return []

        if len(meaningful) <= top_k:
            return [m[:120] for m in meaningful]

        embeddings = self.model.encode(meaningful, normalize_embeddings=True)
        centroid = np.mean(embeddings, axis=0)
        centroid /= np.linalg.norm(centroid)

        sims = [float(np.dot(emb, centroid)) for emb in embeddings]
        top_indices = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:top_k]
        top_indices.sort()

        return [meaningful[i][:120] for i in top_indices]

    def enrich_session(self, user_messages: List[str]) -> Dict:
        """
        Full session enrichment: topics, interaction type, extractive summary.
        Returns: {topics: [...], interaction_type: str, summary: [...]}
        """
        return {
            "topics": self.classify_topics(user_messages),
            "interaction_type": self.classify_interaction_type(user_messages),
            "summary": self.extractive_summary(user_messages),
        }

    def flush_new_topics(self):
        """
        Save any accumulated 'new' topic entries to disk and attempt auto-clustering.
        Call this once at the end of a processing run.
        """
        if not self._new_entries_buffer:
            return

        existing = load_new_topics()
        existing.extend(self._new_entries_buffer)
        self._new_entries_buffer = []

        # Attempt to find clusters among "new" entries
        candidates = self._find_topic_candidates(existing)

        # Remove entries that were absorbed into candidates
        if candidates:
            absorbed_indices = set()
            for c in candidates:
                absorbed_indices.update(c.get("_indices", []))
            existing = [e for i, e in enumerate(existing) if i not in absorbed_indices]

        save_new_topics(existing)
        return candidates

    def _find_topic_candidates(self, entries: List[Dict]) -> List[Dict]:
        """
        Cluster 'new' entries by embedding similarity. If a cluster has >= NEW_TOPIC_CLUSTER_MIN
        members, propose it as a candidate topic. Returns candidate dicts with sample messages
        and a suggested label derived from common keywords.
        """
        if len(entries) < NEW_TOPIC_CLUSTER_MIN:
            return []

        # Rebuild embeddings (stored as lists in JSON)
        embeddings = []
        valid_indices = []
        for i, e in enumerate(entries):
            emb = e.get("embedding")
            if emb:
                embeddings.append(np.array(emb))
                valid_indices.append(i)

        if len(embeddings) < NEW_TOPIC_CLUSTER_MIN:
            return []

        emb_matrix = np.array(embeddings)
        # Normalize
        norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        emb_matrix = emb_matrix / norms

        # Simple greedy clustering: pick seed, absorb similar entries
        used = set()
        clusters = []

        for i in range(len(emb_matrix)):
            if i in used:
                continue
            cluster = [i]
            used.add(i)
            for j in range(i + 1, len(emb_matrix)):
                if j in used:
                    continue
                sim = float(np.dot(emb_matrix[i], emb_matrix[j]))
                if sim >= NEW_CLUSTER_SIM_THRESHOLD:
                    cluster.append(j)
                    used.add(j)
            if len(cluster) >= NEW_TOPIC_CLUSTER_MIN:
                clusters.append(cluster)

        candidates = []
        for cluster in clusters:
            # Collect sample messages from cluster members
            all_msgs = []
            for idx in cluster:
                orig_idx = valid_indices[idx]
                msgs = entries[orig_idx].get("sample_messages", [])
                all_msgs.extend(msgs)

            # Extract common words as a rough label hint
            words = " ".join(all_msgs).lower().split()
            # Filter stop words and short words
            stop = {"the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "for",
                    "and", "or", "but", "it", "this", "that", "with", "on", "at", "by",
                    "from", "can", "you", "i", "we", "me", "my", "do", "not", "don't",
                    "let", "be", "has", "have", "had", "will", "would", "should", "could",
                    "just", "also", "now", "then", "so", "if", "all", "some", "any",
                    "no", "yes", "ok", "please", "thanks", "sure", "right", "get", "make"}
            meaningful = [w for w in words if len(w) > 3 and w not in stop]

            # Count frequency
            from collections import Counter
            freq = Counter(meaningful)
            top_words = [w for w, _ in freq.most_common(6)]
            hint = " ".join(top_words) if top_words else "unknown"

            candidates.append({
                "cluster_size": len(cluster),
                "keyword_hint": hint,
                "sample_messages": all_msgs[:8],
                "dates": list(set(
                    entries[valid_indices[idx]].get("date", "") for idx in cluster
                )),
                "_indices": [valid_indices[idx] for idx in cluster],
            })

        return candidates
