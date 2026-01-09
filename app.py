# app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import math
import os

app = FastAPI(title="Curated Experience Matcher v1")

# ----------------------------
# 1) Example "experience inventory"
# Replace this with Airtable/Sheet/DB later
# ----------------------------
EXPERIENCES = [
    {
        "id": "paint_sip_001",
        "title": "Paint & Sip Night",
        "location_zone": "New Kingston",
        "time_slot": "evening",  # morning/day/evening/night
        "activity_level": 2,
        "noise_level": 2,
        "social_intensity": 4,
        "spontaneity_friendly": 3,
        "distance_class": 3,
        "vibes": ["creative", "chill", "date-friendly"],
        "music": ["rnb", "afrobeats", "reggae"],
        "diet_supported": ["vegetarian_options"],
        "transport_friendly": ["rideshare", "drive"]
    },
    {
        "id": "pickleball_001",
        "title": "Pickleball Social",
        "location_zone": "Liguanea",
        "time_slot": "day",
        "activity_level": 6,
        "noise_level": 3,
        "social_intensity": 5,
        "spontaneity_friendly": 5,
        "distance_class": 4,
        "vibes": ["active", "social"],
        "music": [],
        "diet_supported": [],
        "transport_friendly": ["drive", "rideshare"]
    },
    {
        "id": "club_night_001",
        "title": "Dancehall Club Night",
        "location_zone": "New Kingston",
        "time_slot": "night",
        "activity_level": 4,
        "noise_level": 7,
        "social_intensity": 6,
        "spontaneity_friendly": 6,
        "distance_class": 3,
        "vibes": ["party", "high-energy"],
        "music": ["dancehall", "soca", "afrobeats"],
        "diet_supported": [],
        "transport_friendly": ["rideshare", "drive"]
    },
    {
        "id": "cooking_class_001",
        "title": "Cooking Class Experience",
        "location_zone": "Barbican",
        "time_slot": "evening",
        "activity_level": 3,
        "noise_level": 2,
        "social_intensity": 4,
        "spontaneity_friendly": 2,
        "distance_class": 4,
        "vibes": ["creative", "learning", "foodie"],
        "music": [],
        "diet_supported": ["vegetarian_options", "gluten_free_possible"],
        "transport_friendly": ["drive", "rideshare"]
    },
]

# ----------------------------
# 2) Weights
# ----------------------------
WEIGHTS = {
    "activity_level": 2.0,
    "distance_class": 2.0,
    "noise_level": 1.7,
    "social_intensity": 1.5,
    "spontaneity_friendly": 1.1,
    "time_slot": 1.3,
}

# ----------------------------
# 3) Helper functions
# ----------------------------
def clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))

def closeness_1_to_7(user: int, exp: int) -> float:
    """Returns 0..1 closeness; 1 is perfect match."""
    diff = abs(user - exp)  # 0..6
    return 1.0 - (diff / 6.0)

def time_slot_from_energy_time(energy_time_1_to_7: int) -> str:
    # 1..3 = night, 4 = evening, 5 = day, 6..7 = morning
    if energy_time_1_to_7 <= 3:
        return "night"
    if energy_time_1_to_7 == 4:
        return "evening"
    if energy_time_1_to_7 == 5:
        return "day"
    return "morning"

def time_match(user_slot: str, exp_slot: str) -> float:
    # perfect = 1, adjacent = 0.66, far = 0.33
    order = ["morning", "day", "evening", "night"]
    ui, ei = order.index(user_slot), order.index(exp_slot)
    d = abs(ui - ei)
    if d == 0:
        return 1.0
    if d == 1:
        return 0.66
    if d == 2:
        return 0.33
    return 0.0

def social_intensity_from_user(social_energy: int, talkativeness: int) -> int:
    # average then clamp to 1..7
    return int(round(clamp((social_energy + talkativeness) / 2.0, 1, 7)))

def distance_class_from_user(distance_tolerance: int, transport_tags: List[str]) -> int:
    """
    Convert user's distance tolerance + transport to recommended distance_class 1..7.
    If walkable-only present, cap hard.
    """
    if "walkable" in transport_tags:
        return 1  # must be walkable
    if "public" in transport_tags and "drive" not in transport_tags:
        # cap a bit, because public transit limits late-night + far trips
        return min(distance_tolerance, 4)
    return distance_tolerance

def hard_filter(user: Dict[str, Any], exp: Dict[str, Any]) -> bool:
    # transport hard constraint
    if "walkable" in user["transport_tags"] and exp["distance_class"] > 2:
        return False

    # cuisine avoid (if you later tag cuisines on experiences)
    # dietary restriction check
    for r in user.get("diet_restrictions", []):
        # very simple rule: if user has restriction and exp doesn't list support, still allow unless it's strict.
        # You can tighten later.
        pass

    # transport friendliness (optional)
    # If user relies on public only and experience isn't public-friendly, you may downrank instead of exclude.
    return True

def compute_score(user: Dict[str, Any], exp: Dict[str, Any]) -> float:
    # Derived user targets
    user_time_slot = time_slot_from_energy_time(user["energy_time"])
    user_social_intensity = social_intensity_from_user(user["social_energy"], user["talkativeness"])
    user_distance_class = distance_class_from_user(user["distance_tolerance"], user["transport_tags"])

    # Weighted similarity
    score = 0.0
    score += WEIGHTS["activity_level"] * closeness_1_to_7(user["activity_level"], exp["activity_level"])
    score += WEIGHTS["distance_class"] * closeness_1_to_7(user_distance_class, exp["distance_class"])
    score += WEIGHTS["noise_level"] * closeness_1_to_7(user["noise_tolerance"], exp["noise_level"])
    score += WEIGHTS["social_intensity"] * closeness_1_to_7(user_social_intensity, exp["social_intensity"])
    score += WEIGHTS["spontaneity_friendly"] * closeness_1_to_7(user["spontaneity"], exp["spontaneity_friendly"])
    score += WEIGHTS["time_slot"] * time_match(user_time_slot, exp["time_slot"])

    # Boosts
    # goal boost
    goal = user.get("goal", "")
    if goal and goal in exp.get("vibes", []):
        score += 0.75

    # music overlap boost
    if user.get("music", []) and exp.get("music", []):
        overlap = len(set([m.lower() for m in user["music"]]) & set([m.lower() for m in exp["music"]]))
        if overlap > 0:
            score += min(0.6, 0.2 * overlap)

    return score

# ----------------------------
# 4) Payload model (what webhook posts)
# ----------------------------
class Submission(BaseModel):
    # numeric 1..7
    social_energy: int
    talkativeness: int
    energy_time: int
    noise_tolerance: int
    spontaneity: int
    activity_level: int
    distance_tolerance: int

    # lists / tags
    transport_tags: List[str] = []
    music: List[str] = []
    diet_restrictions: List[str] = []
    goal: Optional[str] = None

    # optional metadata
    contact_id: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None

@app.post("/match")
def match(sub: Submission):
    user = sub.model_dump()

    # basic validation
    for k in ["social_energy", "talkativeness", "energy_time", "noise_tolerance", "spontaneity", "activity_level", "distance_tolerance"]:
        v = user[k]
        if not (1 <= v <= 7):
            raise HTTPException(status_code=400, detail=f"{k} must be 1..7")

    candidates = []
    for exp in EXPERIENCES:
        if not hard_filter(user, exp):
            continue
        s = compute_score(user, exp)
        candidates.append({"id": exp["id"], "title": exp["title"], "score": round(s, 3)})

    candidates.sort(key=lambda x: x["score"], reverse=True)

    # return top 5
    return {
        "top": candidates[:5],
        "debug": {
            "derived_time_slot": time_slot_from_energy_time(user["energy_time"]),
            "derived_social_intensity": social_intensity_from_user(user["social_energy"], user["talkativeness"]),
        }
    }
