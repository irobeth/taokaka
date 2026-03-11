import asyncio
import math
import time
import uuid
from datetime import datetime

import requests

from constants import AI_NAME, BANNED_TOKENS, HOST_NAME, LLM_ENDPOINT
from prompts import load_prompt, strip_think
from modules.module import Module

_MOOD_PROMPT = load_prompt("mood")

# Plutchik's 8 primary emotions mapped to polar angle (degrees)
EMOTION_ANGLES = {
    "joy": 0,
    "trust": 45,
    "fear": 90,
    "surprise": 135,
    "sadness": 180,
    "disgust": 225,
    "anger": 270,
    "anticipation": 315,
}

# Emoji mapping: each emotion has [low, mid, high] intensity variants
EMOTION_EMOJI = {
    "joy":          ["🙂", "😄", "🤩"],
    "trust":        ["🤝", "💛", "💖"],
    "fear":         ["😟", "😨", "😱"],
    "surprise":     ["😮", "😲", "🤯"],
    "sadness":      ["😕", "😢", "😭"],
    "disgust":      ["😒", "🤢", "🤮"],
    "anger":        ["😤", "😠", "🤬"],
    "anticipation": ["🤔", "👀", "⚡"],
}


def emoji_for_mood(emotion, intensity=0.5):
    """Pick the best emoji for an emotion at a given intensity (0-1)."""
    variants = EMOTION_EMOJI.get(emotion, ["❓", "❓", "❓"])
    if intensity < 0.35:
        return variants[0]
    elif intensity < 0.7:
        return variants[1]
    else:
        return variants[2]


def mood_to_cartesian(emotion, intensity):
    """Convert emotion + intensity to x,y for blending."""
    angle_rad = math.radians(EMOTION_ANGLES.get(emotion, 0))
    return intensity * math.cos(angle_rad), intensity * math.sin(angle_rad)


def cartesian_to_mood(x, y):
    """Convert x,y back to nearest emotion + intensity."""
    intensity = min(1.0, max(0.0, math.sqrt(x * x + y * y)))
    angle_deg = math.degrees(math.atan2(y, x)) % 360
    best, best_dist = "joy", 999
    for emotion, angle in EMOTION_ANGLES.items():
        dist = min(abs(angle - angle_deg), 360 - abs(angle - angle_deg))
        if dist < best_dist:
            best_dist = dist
            best = emotion
    return best, intensity


class MoodExtractor(Module):
    """Evaluates Taokaka's emotional state after each LLM prompt cycle.

    Tracks a global mood as 3D polar coordinates (emotion, intensity, inertia)
    plus per-subject moods (users, topics, keywords) stored in ChromaDB.
    """

    def __init__(self, signals, memory_injector, interface=None, enabled=True):
        super().__init__(signals, enabled)
        self.memory_injector = memory_injector
        self.interface = interface
        self._last_prompt_time = 0.0

        # Initialize default global mood
        self.signals.extractor_signals["mood"] = {
            "emotion": "anticipation",
            "intensity": 0.4,
            "inertia": 0.3,
            "summary": "Tao is alert and ready for whatever happens next.",
            "shift": "Something exciting or funny could easily tip her into joy.",
            "timestamp": time.time(),
            "emoji": emoji_for_mood("anticipation", 0.4),
        }
        self.signals.extractor_signals["subject_moods"] = {}

    def _log(self, msg):
        if self.interface:
            self.interface.trace(msg, source="Mood", level="info")
        else:
            print(f"MOOD: {msg}")

    def _build_recent_exchange(self):
        history = self.signals.history
        if len(history) < 2:
            return ""
        lines = []
        for msg in history[-6:]:
            role = msg.get("role", "")
            content = msg.get("content", "").strip()
            if not content:
                continue
            if role == "assistant":
                lines.append(f"{AI_NAME}: {content}")
            else:
                lines.append(f"{HOST_NAME}: {content}")
        return "\n".join(lines)

    def _format_old_mood(self):
        mood = self.signals.extractor_signals.get("mood", {})
        emotion = mood.get("emotion", "anticipation")
        intensity = mood.get("intensity", 0.4)
        inertia = mood.get("inertia", 0.3)
        summary = mood.get("summary", "neutral and ready")
        return f"{emotion} (intensity: {intensity}, inertia: {inertia})\n{summary}"

    def _llm_call(self, prompt):
        data = {
            "mode": "instruct",
            "max_tokens": 4000,
            "skip_special_tokens": False,
            "custom_token_bans": BANNED_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = requests.post(
            LLM_ENDPOINT + "/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json=data, verify=False, timeout=15,
        )
        return strip_think(resp.json()["choices"][0]["message"]["content"])

    def _parse_mood_response(self, raw):
        """Parse the structured mood response including overall + subject moods."""
        overall = {}
        subjects = []
        current_subject = None

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue

            if line.upper().startswith("OVERALL:"):
                current_subject = None
                continue

            if line.upper().startswith("SUBJECT:"):
                if current_subject and current_subject.get("name"):
                    subjects.append(current_subject)
                current_subject = {"name": line.split(":", 1)[1].strip().lower()}
                continue

            if line.upper().startswith("EMOTION:"):
                val = line.split(":", 1)[1].strip().lower()
                if val in EMOTION_ANGLES:
                    if current_subject is not None:
                        current_subject["emotion"] = val
                    else:
                        overall["emotion"] = val

            elif line.upper().startswith("INTENSITY:"):
                try:
                    v = max(0.0, min(1.0, float(line.split(":", 1)[1].strip())))
                    if current_subject is not None:
                        current_subject["intensity"] = v
                    else:
                        overall["intensity"] = v
                except ValueError:
                    pass

            elif line.upper().startswith("INERTIA:"):
                try:
                    v = max(0.0, min(1.0, float(line.split(":", 1)[1].strip())))
                    if current_subject is not None:
                        current_subject["inertia"] = v
                    else:
                        overall["inertia"] = v
                except ValueError:
                    pass

            elif line.upper().startswith("SUMMARY:"):
                overall["summary"] = line.split(":", 1)[1].strip()

            elif line.upper().startswith("SHIFT:"):
                overall["shift"] = line.split(":", 1)[1].strip()

            elif line.upper().startswith("REASON:"):
                if current_subject is not None:
                    current_subject["reason"] = line.split(":", 1)[1].strip()

        # Don't forget the last subject
        if current_subject and current_subject.get("name"):
            subjects.append(current_subject)

        return overall, subjects

    def _apply_inertia(self, old_mood, new_mood):
        """Blend old and new mood based on old mood's inertia."""
        inertia = old_mood.get("inertia", 0.3)
        blend = 1.0 - inertia

        old_emotion = old_mood.get("emotion", "anticipation")
        new_emotion = new_mood.get("emotion", old_emotion)
        old_intensity = old_mood.get("intensity", 0.4)
        new_intensity = new_mood.get("intensity", old_intensity)

        blended_intensity = old_intensity * inertia + new_intensity * blend

        ox, oy = mood_to_cartesian(old_emotion, old_intensity * inertia)
        nx, ny = mood_to_cartesian(new_emotion, new_intensity * blend)
        blended_emotion, _ = cartesian_to_mood(ox + nx, oy + ny)

        return {
            "emotion": blended_emotion if blend > 0.3 else old_emotion,
            "intensity": round(blended_intensity, 2),
            "inertia": new_mood.get("inertia", old_mood.get("inertia", 0.3)),
            "summary": new_mood.get("summary", old_mood.get("summary", "")),
            "shift": new_mood.get("shift", old_mood.get("shift", "")),
            "timestamp": time.time(),
        }

    # ── ChromaDB subject mood storage ──

    def _get_subject_mood_from_db(self, subject_name):
        """Look up an existing mood memory for this subject."""
        collection = self.memory_injector.collection
        try:
            results = collection.get(where={"type": "mood"})
        except Exception:
            return None
        for i, meta in enumerate(results["metadatas"]):
            if meta.get("title", "").lower() == subject_name.lower():
                return results["ids"][i], results["documents"][i], meta
        return None

    def _store_subject_mood(self, subject):
        """Upsert a mood memory for a subject into ChromaDB."""
        name = subject["name"]
        emotion = subject.get("emotion", "anticipation")
        intensity = subject.get("intensity", 0.5)
        inertia = subject.get("inertia", 0.3)
        reason = subject.get("reason", "")

        collection = self.memory_injector.collection

        # Check for existing mood for this subject
        existing = self._get_subject_mood_from_db(name)

        # Blend with old mood if it exists
        if existing:
            old_id, old_doc, old_meta = existing
            old_emotion = old_meta.get("mood_emotion", "anticipation")
            old_intensity = float(old_meta.get("mood_intensity", "0.5"))
            old_inertia = float(old_meta.get("mood_inertia", "0.3"))
            old_mood = {"emotion": old_emotion, "intensity": old_intensity, "inertia": old_inertia}
            blended = self._apply_inertia(old_mood, subject)
            emotion = blended["emotion"]
            intensity = blended["intensity"]
            inertia = blended.get("inertia", inertia)
            collection.delete(old_id)

        doc = f"Tao feels {emotion} about {name} (intensity: {intensity}). {reason}"
        meta = {
            "type": "mood",
            "related_user": name,
            "keywords": name,
            "title": name,
            "source": "mood_extractor",
            "mood_emotion": emotion,
            "mood_intensity": str(round(intensity, 2)),
            "mood_inertia": str(round(inertia, 2)),
            "created_at": datetime.now().isoformat(),
        }
        collection.upsert(
            [str(uuid.uuid4())],
            documents=[doc],
            metadatas=[meta],
        )
        emj = emoji_for_mood(emotion, intensity)
        self._log(f"  {emj} {name}: {emotion} (i={intensity}, inertia={inertia}) — {reason[:60]}")
        return {"emotion": emotion, "intensity": intensity, "inertia": inertia, "reason": reason, "emoji": emj}

    def _evaluate_mood(self):
        exchange = self._build_recent_exchange()
        if not exchange:
            return

        old_mood_str = self._format_old_mood()
        prompt = _MOOD_PROMPT.format(
            old_mood=old_mood_str,
            recent_exchange=exchange,
        )

        self._log("Evaluating mood...")
        raw = self._llm_call(prompt)
        overall, subjects = self._parse_mood_response(raw)

        if not overall.get("emotion"):
            self._log(f"Failed to parse mood response: {raw[:100]}")
            return

        # Update global mood with inertia blending
        old_mood = self.signals.extractor_signals.get("mood", {})
        blended = self._apply_inertia(old_mood, overall)
        blended["emoji"] = emoji_for_mood(blended["emotion"], blended["intensity"])
        self.signals.extractor_signals["mood"] = blended
        self._log(
            f"Overall: {blended['emoji']} {blended['emotion']} "
            f"(i={blended['intensity']}, inertia={blended['inertia']}) "
            f"— {blended['summary']}"
        )

        # Store per-subject moods in ChromaDB
        subject_moods = {}
        for subject in subjects:
            if not subject.get("emotion") or not subject.get("name"):
                continue
            stored = self._store_subject_mood(subject)
            subject_moods[subject["name"]] = stored

        if subject_moods:
            self.signals.extractor_signals["subject_moods"] = subject_moods

    async def run(self):
        while not self.signals.terminate:
            await asyncio.sleep(2)
            if not self.enabled:
                continue

            prompt_time = self.signals.extractor_signals.get("prompt_completed", 0)
            if prompt_time > self._last_prompt_time:
                self._last_prompt_time = prompt_time
                try:
                    self._evaluate_mood()
                except Exception as e:
                    self._log(f"Error: {e}")
