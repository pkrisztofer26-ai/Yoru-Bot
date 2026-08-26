diff -ruN old/app/ai_director_game_master.py new/app/ai_director_game_master.py
--- old/app/ai_director_game_master.py	2026-08-26 17:23:01.531962254 +0000
+++ new/app/ai_director_game_master.py	2026-08-26 18:00:06.089488911 +0000
@@ -5,7 +5,7 @@
 The Game Master layer may narrate only host-owned facts that were already
 resolved by canonical deterministic services.  It never chooses gameplay truth,
 branches, rewards, success/failure, permissions, inventory or state mutation.
-W22.5 deliberately ships no player-facing call sites.
+W22.5/W22.5.1/W22.5.1.1 deliberately ship no player-facing call sites.
 """
 
 import hashlib
@@ -16,7 +16,7 @@
 from typing import Any, Mapping
 
 
-GAME_MASTER_CONTRACT_VERSION = "tier3-game-master-surface-v1"
+GAME_MASTER_CONTRACT_VERSION = "tier3-game-master-surface-v3"
 GAME_MASTER_RUNTIME_ENABLED_DEFAULT = False
 GAME_MASTER_FAMILIES = frozenset({
     "big_job",
@@ -61,6 +61,20 @@
     r"kimenetel|ág|branch|állapot|hozzáférés)\b",
     re.IGNORECASE | re.DOTALL,
 )
+
+# Human-review-derived Tier 3 presentation quality regressions. These rules are
+# presentation-only and never change gameplay truth; they only force the
+# deterministic fallback when generated Hungarian is awkward or overstates the
+# host-owned facts.
+_HUMAN_DERIVED_SURFACE_REJECTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
+    (re.compile(r"\b(?:részsiker|siker)\s+lezárást\s+kapott\b", re.IGNORECASE), "unnatural_resolution_phrase"),
+    (re.compile(r"\bfelé\s+(?:közeledik|ért)\b", re.IGNORECASE), "unsupported_temporal_progression"),
+    (re.compile(r"\.\s+[a-záéíóöőúüű]", re.UNICODE), "lowercase_sentence_start"),
+    (re.compile(r"\b(?:örökre|legendákban|legendává|emlékezetes(?:\s+kaland)?|mesékben)\b", re.IGNORECASE), "unsupported_embellishment"),
+    (re.compile(r"\b([a-záéíóöőúüű]{3,})\s+\1\b", re.IGNORECASE), "repeated_word"),
+    (re.compile(r"\ba\s+[aáeéiíoóöőuúüű]", re.IGNORECASE), "wrong_hungarian_article"),
+    (re.compile(r"\btörténetszál\s+[^.!?]{1,80}\s+pontja\b", re.IGNORECASE), "awkward_story_beat_phrase"),
+)
 _KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,95}$")
 
 
@@ -73,6 +87,46 @@
     return "".join(ch for ch in decomposed if not unicodedata.combining(ch))
 
 
+def _sentence_lead(value: str) -> str:
+    text = str(value).strip()
+    if not text:
+        return text
+    return text[:1].upper() + text[1:]
+
+
+def game_master_surface_quality_errors(packet: AIDirectorGameMasterPacket, title: str, description: str) -> tuple[str, ...]:
+    merged = f"{str(title).strip()}\n{str(description).strip()}"
+    errors: list[str] = []
+    for pattern, label in _HUMAN_DERIVED_SURFACE_REJECTIONS:
+        if pattern.search(merged):
+            errors.append(label)
+    causal_re = re.compile(
+        r"\b(?:hiszen|mivel|ezért|emiatt|ennek\s+köszönhetően|következtében)\b",
+        re.IGNORECASE,
+    )
+    if packet.family in {"npc_story", "consequence_recall"} and causal_re.search(merged):
+        errors.append("unsupported_memory_causality")
+
+    facts_folded = _fold(" ".join(str(value) for value in packet.facts.values()))
+    merged_folded = _fold(merged)
+    # Human-review-derived ambient/world expansion tokens. These are allowed only
+    # when the host facts already contain the same concept.
+    for token in ("kornyek", "pletyka", "sajto", "tanu", "hatosag"):
+        if token in merged_folded and token not in facts_folded:
+            errors.append("unsupported_ambient_expansion")
+            break
+    if packet.family == "world_story":
+        beat = _fold(packet.facts.get("beat_title", "")).strip()
+        if beat and re.search(re.escape(beat) + r"[^a-z0-9]{0,4}pontja\b", merged_folded):
+            errors.append("awkward_story_beat_phrase")
+    if packet.family == "legendary_event":
+        for token in ("emlek", "mese"):
+            if token in merged_folded and token not in facts_folded:
+                errors.append("unsupported_legacy_reframing")
+                break
+    return tuple(errors)
+
+
 @dataclass(frozen=True, slots=True)
 class AIDirectorGameMasterPacket:
     story_key: str
@@ -163,6 +217,11 @@
         raise AIDirectorGameMasterValidationError("A Tier 3 AI belső rendszerzsargont próbált player-facing szövegbe tenni.")
     if _FORBIDDEN_AUTHORITY_CLAIM_RE.search(merged):
         raise AIDirectorGameMasterValidationError("A Tier 3 AI authority-jellegű állítást próbált tenni.")
+    quality_errors = game_master_surface_quality_errors(packet, title, description)
+    if quality_errors:
+        raise AIDirectorGameMasterValidationError(
+            "A Tier 3 AI human-review quality guardon bukott: " + ",".join(quality_errors)
+        )
     folded = _fold(merged)
     for term in packet.required_terms:
         anchor = _fold(str(term).strip())
@@ -212,7 +271,7 @@
         {"target_name": target_name, "phase_label": phase_label, "approach_label": approach_label, "route_label": route_label,
          "host_resolution": host_resolution, "consequence_note": consequence_note},
         "A Nagy Meló visszhangja",
-        f"A {target_name} akció {host_resolution} lezárást kapott. A {approach_label} megközelítés és a {route_label} útvonal után ez maradt meg a történetből: {consequence_note}",
+        f"„{target_name}” — az akció lezárása: {host_resolution}. Megközelítés: {approach_label}. Útvonal: {route_label}. {_sentence_lead(consequence_note)}.",
         required=(target_name, host_resolution),
     )
 
@@ -223,7 +282,7 @@
         {"npc_name": npc_name, "npc_role": npc_role, "relationship_band": relationship_band,
          "recalled_event": recalled_event, "current_story_state": current_story_state},
         f"{npc_name} emlékszik",
-        f"{npc_name} ({npc_role}) számára továbbra is számít, hogy {recalled_event}. A kapcsolat jelenlegi hangulata: {relationship_band}; a történeti helyzet: {current_story_state}.",
+        f"{npc_name}, {npc_role}. A kapcsolat jelenlegi hangulata: {relationship_band}. Felidézett esemény: {_sentence_lead(recalled_event)}. Jelenlegi történeti helyzet: {_sentence_lead(current_story_state)}.",
         required=(npc_name, recalled_event),
     )
 
@@ -234,7 +293,7 @@
         {"subject_label": subject_label, "memory_category": memory_category, "remembered_event": remembered_event,
          "current_relevance": current_relevance},
         "Egy régi döntés visszhangja",
-        f"{subject_label} kapcsán újra előkerül, hogy {remembered_event}. Ez most azért releváns, mert {current_relevance}.",
+        f"{_sentence_lead(subject_label)} kapcsán újra előkerül, hogy {remembered_event}. A jelenlegi összefüggés: {current_relevance}.",
         required=(subject_label, remembered_event),
     )
 
@@ -243,10 +302,10 @@
     facts = {"chapter_title": chapter_title, "stage_title": stage_title, "world_story_title": world_story_title, "community_note": community_note}
     if host_ending:
         facts["host_ending"] = host_ending
-        desc = f"A {chapter_title} fejezete a {stage_title} szakasz után a {host_ending} lezárás felé ért. A háttérben {world_story_title}; {community_note}."
+        desc = f"A „{chapter_title}” fejezet lezárása: {host_ending}. Utolsó szakasz: {stage_title}. Háttértörténet: {world_story_title}. {_sentence_lead(community_note)}."
         required = (chapter_title, host_ending)
     else:
-        desc = f"A {chapter_title} jelenleg a {stage_title} szakaszban jár. A háttérben {world_story_title}; {community_note}."
+        desc = f"A „{chapter_title}” fejezet jelenlegi szakasza: {stage_title}. Háttértörténet: {world_story_title}. {_sentence_lead(community_note)}."
         required = (chapter_title, stage_title)
     return _packet("chapter", "chapter_scene", facts, "A fejezet helyzete", desc, required=required)
 
@@ -257,7 +316,7 @@
         {"national_title": national_title, "story_title": story_title, "beat_title": beat_title,
          "city_label": city_label, "world_note": world_note},
         story_title,
-        f"{national_title} hátterében a {story_title} történetszál {beat_title} pontja került előtérbe {city_label} körül. {world_note}",
+        f"Országos háttér: „{national_title}”. Történetszál: „{story_title}”. Aktuális pont: „{beat_title}”. Helyszín: {city_label}. {_sentence_lead(world_note)}.",
         required=(story_title, beat_title),
     )
 
@@ -268,6 +327,6 @@
         {"event_name": event_name, "access_context": access_context, "phase_label": phase_label,
          "host_resolution": host_resolution, "legacy_note": legacy_note},
         "Legendás ügy",
-        f"A {event_name} története a {phase_label} pont után {host_resolution} lezárást kapott. Ami megmaradt belőle: {legacy_note}",
+        f"„{event_name}” történetének lezárása: {host_resolution}. Szakasz: {phase_label}. {_sentence_lead(legacy_note)}.",
         required=(event_name, host_resolution),
     )
diff -ruN old/app/providers/ai_director_game_master_groq.py new/app/providers/ai_director_game_master_groq.py
--- old/app/providers/ai_director_game_master_groq.py	2026-08-26 17:23:01.537155759 +0000
+++ new/app/providers/ai_director_game_master_groq.py	2026-08-26 18:00:06.094208695 +0000
@@ -8,17 +8,20 @@
 
 
 class GroqAIDirectorGameMasterProvider(GroqAIDirectorProvider):
-    """Non-player review provider for the W22.5 Tier 3 foundation."""
+    """Non-player review provider for the W22.5.1.1 Tier 3 hardening gate."""
 
     @staticmethod
     def system_prompt() -> str:
         return (
             "Te a Yoru Tier 3 AI Game Master presentation-only magyar narrátorrétege vagy. "
             "A HOST_FACTS már eldöntött, host-owned történeti tények. Ezeket kizárólag hangulatos, rövid magyar "
-            "narrációvá formálhatod. Nem találhatsz ki új szereplőt, helyet, múltbeli eseményt, branch-et, választást, "
+            "narrációvá formálhatod természetes, idiomatikus magyar nyelven. Nem találhatsz ki új szereplőt, helyet, múltbeli eseményt, branch-et, választást, "
             "jutalomról vagy esélyről új állítást, mechanikát vagy következményt. Nem módosíthatod és nem döntheted el "
             "a host_resolution, ending, memory vagy world-state értékét. Nem dönthetsz sikerről, kudarcról, jutalomról, "
             "pénzről, XP-ről, inventoryról, cooldownról vagy engedélyről. Ne használj belső rendszerzsargont (canonical, "
             "authority, mechanika, validator, fallback, provider, contract). A válasz pontosan title és description legyen. "
+            "Ne gyárts oksági kapcsolatot a felidézett esemény és a jelenlegi kapcsolat között (például hiszen, mivel, ezért, emiatt), ha azt a HOST_FACTS nem mondja ki. "
+            "Ne találj ki környék-, sajtó-, pletyka-, tanú- vagy hatósági reakciót. Ne ígérj örök emléket, legendává válást vagy más extra örökséget. "
+            "Kerüld a merev 'siker/részsiker lezárást kapott' és 'történetszál ... pontja' fordulatokat. "
             "Semmit ne írj a JSON-on kívül."
         )
 
diff -ruN old/scripts/ai_director_tier3_game_master_review.py new/scripts/ai_director_tier3_game_master_review.py
--- old/scripts/ai_director_tier3_game_master_review.py	2026-08-26 17:23:01.538293685 +0000
+++ new/scripts/ai_director_tier3_game_master_review.py	2026-08-26 18:00:06.095112542 +0000
@@ -7,7 +7,7 @@
 from pathlib import Path
 from typing import Any, Mapping
 
-from app.ai_director_game_master import GAME_MASTER_CONTRACT_VERSION, fallback_game_master_surface, validate_game_master_surface
+from app.ai_director_game_master import GAME_MASTER_CONTRACT_VERSION, fallback_game_master_surface, validate_game_master_surface, AIDirectorGameMasterValidationError
 from app.providers.ai_director_game_master_groq import GroqAIDirectorGameMasterProvider
 
 
@@ -27,9 +27,9 @@
         self._i += 1
         return dict(self._responses[(self._i - 1) % len(self._responses)])
 
-VERSION = "3.83.7"
-WORK_ITEM = "W22.5"
-REVIEW_TITLE = "Tier 3 Game Master Foundation Review"
+VERSION = "3.83.9"
+WORK_ITEM = "W22.5.1.1"
+REVIEW_TITLE = "Tier 3 Game Master Provider Review"
 
 
 def packets():
@@ -132,13 +132,29 @@
         err_detail = ""
         try:
             raw = await provider.generate_game_master(packet)
-            title, description = validate_game_master_surface(packet, raw)
+            try:
+                title, description = validate_game_master_surface(packet, raw)
+            except AIDirectorGameMasterValidationError as exc:
+                err_type = "validation"
+                err_detail = str(exc)[:500]
+                fallback = fallback_game_master_surface(packet)
+                title, description = fallback.title, fallback.description
             source = "ai_game_master"
+            if err_type:
+                source = "deterministic_scenario_v2_fallback"
         except Exception as exc:
             fallback = fallback_game_master_surface(packet)
             title, description = fallback.title, fallback.description
             source = "deterministic_scenario_v2_fallback"
             err_type = type(exc).__name__
             err_detail = str(exc)[:500]
+        effective_valid = True
+        try:
+            validate_game_master_surface(packet, {"title": title, "description": description})
+        except AIDirectorGameMasterValidationError as exc:
+            effective_valid = False
+            if not err_type:
+                err_type = "effective_validation"
+                err_detail = str(exc)[:500]
         rows.append({
             "index": i, "story_key": packet.story_key, "family": packet.family,
             "semantic_slot": packet.semantic_slot, "packet_digest": packet.digest,
@@ -147,6 +163,7 @@
             "description": description, "title_length": len(title), "description_length": len(description),
             "error_type": err_type, "error_detail": err_detail,
             "player_facing_ai": False, "gameplay_authority": "NONE", "live_deploy": False,
+            "effective_valid": effective_valid,
         })
         if mode == "live" and i < len(items):
             await asyncio.sleep(2.0)
@@ -156,10 +173,11 @@
     if dupes:
         print("DUPLICATES", dupes)
     fallbacks = sum(1 for row in rows if row["source"] != "ai_game_master")
-    status = "PENDING_HUMAN" if fallbacks == 0 else "AUTOMATED_HOLD"
+    effective_validated = sum(1 for row in rows if row.get("effective_valid"))
+    status = "PENDING_HUMAN" if effective_validated == len(rows) else "AUTOMATED_HOLD"
     human_rows = [dict(row, human_decision="PENDING", human_notes="") for row in rows]
     payload = {
         "version": VERSION, "work_item": WORK_ITEM, "contract": GAME_MASTER_CONTRACT_VERSION, "mode": mode,
-        "total": len(rows), "ai_validated": len(rows) - fallbacks, "fallbacks": fallbacks,
+        "total": len(rows), "ai_validated": len(rows) - fallbacks, "fallbacks": fallbacks, "effective_validated": effective_validated,
         "duplicate_groups": dupes, "status": status, "rows": rows,
         "player_facing_ai": False, "gameplay_authority": "NONE", "live_deploy": False,
     }
@@ -172,6 +190,7 @@
         f"STATUS={status}",
         f"TOTAL={len(rows)}",
         f"AI_VALIDATED={len(rows) - fallbacks}",
         f"FALLBACKS={fallbacks}",
+        f"EFFECTIVE_VALIDATED={effective_validated}",
         "PLAYER_FACING_AI=OFF",
         "GAMEPLAY_AUTHORITY=NONE",
         "LIVE_DEPLOY=UNCHANGED",
@@ -179,7 +198,7 @@
     ]) + "\n", encoding="utf-8")
     print((output / "YORU_AI_DIRECTOR_TIER3_GAME_MASTER_REVIEW_RESULT.txt").read_text(encoding="utf-8"))
-    return 0 if fallbacks == 0 else 2
+    return 0 if effective_validated == len(rows) else 2
 
 
 def main() -> int:
diff -ruN old/tests/test_w22_5_game_master_ci.py new/tests/test_w22_5_game_master_ci.py
--- old/tests/test_w22_5_game_master_ci.py	2026-08-26 17:23:01.539100771 +0000
+++ new/tests/test_w22_5_game_master_ci.py	2026-08-26 18:00:06.096953881 +0000
@@ -1,54 +1,251 @@
 from __future__ import annotations
-import asyncio
-import pytest
-from app.ai_director_game_master import *
-from app.services.ai_director_game_master import AIDirectorGameMaster
-from app.providers.ai_director_game_master_groq import GroqAIDirectorGameMasterProvider
+
+import asyncio
+from pathlib import Path
+
+import pytest
+
+from app.ai_director_game_master import (
+    GAME_MASTER_CONTRACT_VERSION,
+    GAME_MASTER_FAMILIES,
+    GAME_MASTER_RUNTIME_ENABLED_DEFAULT,
+    AIDirectorGameMasterPacket,
+    AIDirectorGameMasterValidationError,
+    big_job_packet,
+    chapter_packet,
+    consequence_recall_packet,
+    fallback_game_master_surface,
+    legendary_event_packet,
+    npc_story_packet,
+    validate_game_master_packet,
+    validate_game_master_surface,
+    world_story_packet,
+)
+from app.providers.ai_director_game_master_groq import GroqAIDirectorGameMasterProvider
+from app.services.ai_director_game_master import AIDirectorGameMaster
 
 
-def run(c): return asyncio.run(c)
-def p(): return big_job_packet(target_name='Belvárosi trezor',phase_label='menekülés',approach_label='csendes',route_label='hátsó útvonal',host_resolution='részsiker',consequence_note='a csapat szétszóródva jutott ki')
-class Fake:
-    def __init__(self, raw=None, error=None): self.raw=raw or {'title':'A Belvárosi trezor visszhangja','description':'A Belvárosi trezor akció részsikerrel zárult, és a csapat szétszóródva jutott ki.'}; self.error=error; self.calls=0
-    async def generate_game_master(self, packet):
+def run(coro):
+    return asyncio.run(coro)
+
+
+def big():
+    return big_job_packet(
+        target_name="Belvárosi trezor",
+        phase_label="menekülés",
+        approach_label="csendes",
+        route_label="hátsó útvonal",
+        host_resolution="részsiker",
+        consequence_note="a csapat szétszóródva jutott ki",
+    )
+
+
+class FakeProvider:
+    def __init__(self, raw=None, error=None):
+        self.raw = raw or {
+            "title": "A Belvárosi trezor visszhangja",
+            "description": "A Belvárosi trezor akció részsikerrel zárult, és a csapat szétszóródva jutott ki.",
+        }
+        self.error = error
+        self.calls = 0
+
+    async def generate_game_master(self, _packet):
         self.calls += 1
-        if self.error: raise self.error
+        if self.error:
+            raise self.error
         return self.raw
-def test_identity(): assert GAME_MASTER_CONTRACT_VERSION=='tier3-game-master-surface-v1' and GAME_MASTER_RUNTIME_ENABLED_DEFAULT is False
-def test_families(): assert GAME_MASTER_FAMILIES=={'big_job','npc_story','consequence_recall','chapter','world_story','legendary_event'}
-@pytest.mark.parametrize('packet',[
- p(),
- npc_story_packet(npc_name='Zoli',npc_role='kapcsolattartó',relationship_band='óvatos',recalled_event='betartottad a megállapodást',current_story_state='újra szóba áll veled'),
- consequence_recall_packet(subject_label='a riválisod',memory_category='rival',remembered_event='a konfliktus lezáratlan maradt',current_relevance='ugyanabban a körben mozogtok'),
- chapter_packet(chapter_title='Repedések a városban',stage_title='Lezárás',world_story_title='Feszült egyensúly',community_note='a közösségi döntések nyomot hagytak',host_ending='Törékeny egyensúly'),
- world_story_packet(national_title='Országos bizonytalanság',story_title='Feszült egyensúly',beat_title='Új törésvonal',city_label='Budapest',world_note='a helyi szereplők kivárnak'),
- legendary_event_packet(event_name='Fekete Korona',access_context='ritka meghívás után indult',phase_label='végjáték',host_resolution='részsiker',legacy_note='az ügy neve megmaradt a városi történetekben'),
-])
-def test_builders(packet): assert validate_game_master_packet(packet) is packet
-@pytest.mark.parametrize('key',['reward','payout','score','weights','trust_score','chance','success','outcome','choice','branch','user_id','run_id'])
-def test_authority_facts_rejected(key):
-    q=p(); bad=AIDirectorGameMasterPacket(q.story_key,q.family,q.semantic_slot,q.fallback_title,q.fallback_description,{key:'x'})
-    with pytest.raises(AIDirectorGameMasterValidationError): validate_game_master_packet(bad)
-def test_valid_surface(): assert validate_game_master_surface(p(),{'title':'A Belvárosi trezor','description':'A Belvárosi trezor akció részsikerrel zárult.'})[0]
-def test_extra_field_rejected():
-    with pytest.raises(AIDirectorGameMasterValidationError): validate_game_master_surface(p(),{'title':'A Belvárosi trezor','description':'A Belvárosi trezor akció részsikerrel zárult.','branch':'x'})
-def test_mechanical_output_rejected():
-    with pytest.raises(AIDirectorGameMasterValidationError): validate_game_master_surface(p(),{'title':'A Belvárosi trezor','description':'A Belvárosi trezor után biztosan nyersz jutalmat.'})
-def test_jargon_output_rejected():
-    with pytest.raises(AIDirectorGameMasterValidationError): validate_game_master_surface(p(),{'title':'A Belvárosi trezor','description':'A Belvárosi trezor canonical fallback szerint részsiker.'})
-def test_fallback(): assert fallback_game_master_surface(p()).source=='deterministic_scenario_v2_fallback'
-def test_default_off_wrong_guild():
-    f=Fake(); gm=AIDirectorGameMaster(provider=f,enabled=False,test_guild_id=10); assert run(gm.surface(10,p())) is None
-    gm=AIDirectorGameMaster(provider=f,enabled=True,test_guild_id=10); assert run(gm.surface(11,p())) is None and f.calls==0
-def test_provider_error_fallback(): assert run(AIDirectorGameMaster(provider=Fake(error=RuntimeError('x')),enabled=True,test_guild_id=10).surface(10,p())).source=='deterministic_scenario_v2_fallback'
-def test_provider_valid(): assert run(AIDirectorGameMaster(provider=Fake(),enabled=True,test_guild_id=10).surface(10,p())).source=='ai_game_master'
-def test_prompt_and_schema():
-    assert 'nem dönthetsz' in GroqAIDirectorGameMasterProvider.system_prompt().casefold()
-    assert 'host_facts' in GroqAIDirectorGameMasterProvider.user_prompt(p()).casefold()
-    s=GroqAIDirectorGameMasterProvider.output_schema(); assert s['additionalProperties'] is False and set(s['properties'])=={'title','description'}
+
+
+def test_contract_identity_and_default_off():
+    assert GAME_MASTER_CONTRACT_VERSION == "tier3-game-master-surface-v3"
+    assert GAME_MASTER_RUNTIME_ENABLED_DEFAULT is False
+
+
+def test_tier3_families_are_exactly_roadmap_families():
+    assert GAME_MASTER_FAMILIES == {
+        "big_job", "npc_story", "consequence_recall", "chapter", "world_story", "legendary_event"
+    }
+
+
+@pytest.mark.parametrize("packet", [
+    big(),
+    npc_story_packet(npc_name="Zoli", npc_role="kapcsolattartó", relationship_band="óvatos", recalled_event="betartottad a megállapodást", current_story_state="újra szóba áll veled"),
+    consequence_recall_packet(subject_label="a riválisod", memory_category="rival", remembered_event="a konfliktus lezáratlan maradt", current_relevance="ugyanabban a körben mozogtok"),
+    chapter_packet(chapter_title="Repedések a városban", stage_title="Lezárás", world_story_title="Feszült egyensúly", community_note="a közösségi döntések nyomot hagytak", host_ending="Törékeny egyensúly"),
+    world_story_packet(national_title="Országos bizonytalanság", story_title="Feszült egyensúly", beat_title="Új törésvonal", city_label="Budapest", world_note="a helyi szereplők kivárnak"),
+    legendary_event_packet(event_name="Fekete Korona", access_context="ritka meghívás után indult", phase_label="végjáték", host_resolution="részsiker", legacy_note="az ügy neve megmaradt a városi történetekben"),
+])
+def test_all_family_builders_validate(packet):
+    assert validate_game_master_packet(packet) is packet
+    assert packet.digest
+
+
+@pytest.mark.parametrize("key", [
+    "reward", "payout", "amount", "money", "wallet", "xp", "inventory", "cooldown",
+    "chance", "probability", "roll", "success", "outcome", "choice", "branch", "user_id",
+])
+def test_gameplay_authority_fact_keys_are_rejected(key):
+    packet = big()
+    bad = AIDirectorGameMasterPacket(
+        story_key=packet.story_key,
+        family=packet.family,
+        semantic_slot=packet.semantic_slot,
+        fallback_title=packet.fallback_title,
+        fallback_description=packet.fallback_description,
+        facts={**packet.facts, key: "x"},
+        required_terms=packet.required_terms,
+    )
+    with pytest.raises(AIDirectorGameMasterValidationError):
+        validate_game_master_packet(bad)
+
+
+@pytest.mark.parametrize("description", [
+    "A Belvárosi trezor után 20% extra jutalom jár.",
+    "A Belvárosi trezor sikeres lett, ezért nyersz pénzt.",
+    "A Belvárosi trezor új branch-et nyit.",
+    "A Belvárosi trezor növeli az esélyedet.",
+])
+def test_mechanical_or_authority_output_is_rejected(description):
+    with pytest.raises(AIDirectorGameMasterValidationError):
+        validate_game_master_surface(big(), {"title": "A Belvárosi trezor", "description": description})
+
+
+@pytest.mark.parametrize("description", [
+    "A Belvárosi trezor canonical fallback szerint részsiker.",
+    "A Belvárosi trezor mechanikai validator eredménye részsiker.",
+])
+def test_internal_jargon_is_rejected(description):
+    with pytest.raises(AIDirectorGameMasterValidationError):
+        validate_game_master_surface(big(), {"title": "A Belvárosi trezor", "description": description})
+
+
+@pytest.mark.parametrize("description", [
+    "A Belvárosi trezor részsiker lezárást kapott.",
+    "A Repedések a városban fejezet a Törékeny egyensúly lezárás felé közeledik.",
+    "A Feszült egyensúly új pontja előtérbe került. a helyi szereplők kivárnak",
+    "A Fekete Korona neve örökre megmaradt a legendákban.",
+    "Az Éjféli Konvoj emlékezetes kaland maradt.",
+    "A hátsó útvonal útvonal maradt.",
+    "A ipari útvonal került elő.",
+    "A Belvárosi trezor híre a környéknek gyorsan eljutott.",
+    "A Feszült egyensúly történetszál Új törésvonal pontja került előtérbe.",
+    "A Csendes közeledés pontja kerül előtérbe Szeged körül.",
+    "A Fekete Korona neve a városi mesékben maradt meg.",
+])
+def test_human_review_quality_regressions_rejected(description):
+    with pytest.raises(AIDirectorGameMasterValidationError):
+        validate_game_master_surface(big(), {"title": "A Belvárosi trezor", "description": description})
+
+
+@pytest.mark.parametrize("description", [
+    "Zoli óvatos, hiszen emlékszik a régi megállapodásra.",
+    "Mira ezért bizalmatlan maradt veled szemben.",
+    "Mira mivel emlékszik a régi ügyre, bizalmatlan maradt.",
+])
+def test_npc_story_unsupported_causality_rejected(description):
+    packet = npc_story_packet(npc_name="Mira", npc_role="informátor", relationship_band="bizalmatlan", recalled_event="egy régi ügyben cserben hagytad", current_story_state="távolságot tart")
+    with pytest.raises(AIDirectorGameMasterValidationError):
+        validate_game_master_surface(packet, {"title": "Mira emlékszik", "description": description + " Mira egy régi ügyben cserben hagytad."})
+
+
+def test_consequence_recall_unsupported_causality_rejected():
+    packet = consequence_recall_packet(subject_label="a régi üzlettárs", memory_category="agreement", remembered_event="a megállapodást végül teljesítetted", current_relevance="ismét felmerült a közös múlt")
+    with pytest.raises(AIDirectorGameMasterValidationError):
+        validate_game_master_surface(packet, {"title": "Egy régi döntés visszhangja", "description": "A régi üzlettárs kapcsán a megállapodást végül teljesítetted, hiszen ismét felmerült a közös múlt."})
+
+
+def test_world_story_quoted_beat_point_phrase_rejected():
+    packet = world_story_packet(national_title="Lassú rendeződés", story_title="Új kapcsolatok", beat_title="Csendes közeledés", city_label="Szeged", world_note="a helyi hangulat óvatosan enyhül")
+    with pytest.raises(AIDirectorGameMasterValidationError):
+        validate_game_master_surface(packet, {"title": "Új kapcsolatok", "description": "A Lassú rendeződés hátterében a „Csendes közeledés” pontja kerül előtérbe Szeged körül, ahol a helyi hangulat óvatosan enyhül."})
+
+
+def test_legendary_unsupported_legacy_reframing_rejected():
+    packet = legendary_event_packet(event_name="Éjféli Konvoj", access_context="különleges opportunity nyitotta meg", phase_label="lezárás", host_resolution="siker", legacy_note="a résztvevők története később is előkerül")
+    with pytest.raises(AIDirectorGameMasterValidationError):
+        validate_game_master_surface(packet, {"title": "Legendás ügy", "description": "Az Éjféli Konvoj sikerrel zárult, a résztvevők emléke később is felbukkan."})
+
+
+def test_fallbacks_use_natural_sentence_leads_and_resolution_language():
+    b = fallback_game_master_surface(big())
+    assert "részsiker lezárást kapott" not in b.description.casefold()
+    assert "útvonal útvonal" not in b.description.casefold()
+    assert "a ipari" not in b.description.casefold()
+    c = consequence_recall_packet(subject_label="a riválisod", memory_category="rival", remembered_event="a konfliktus lezáratlan maradt", current_relevance="ugyanabban a körben mozogtok")
+    assert c.fallback_description.startswith("A riválisod")
+    assert "azért releváns, mert" not in c.fallback_description.casefold()
+    assert "A jelenlegi összefüggés:" in c.fallback_description
+    n = npc_story_packet(npc_name="Mira", npc_role="informátor", relationship_band="bizalmatlan", recalled_event="egy régi ügyben cserben hagytad", current_story_state="távolságot tart")
+    assert "számít, hogy" not in n.fallback_description
+    assert "Felidézett esemény:" in n.fallback_description
+    w = world_story_packet(national_title="Országos bizonytalanság", story_title="Feszült egyensúly", beat_title="Új törésvonal", city_label="Budapest", world_note="a helyi szereplők kivárnak")
+    assert ". A helyi szereplők" in w.fallback_description
+    assert "Történetszál: „Feszült egyensúly”." in w.fallback_description
+    assert "Aktuális pont: „Új törésvonal”." in w.fallback_description
+    assert "történetszál „Új törésvonal” pontja" not in w.fallback_description
+    w2 = world_story_packet(national_title="Lassú rendeződés", story_title="Új kapcsolatok", beat_title="Csendes közeledés", city_label="Szeged", world_note="a helyi hangulat óvatosan enyhül")
+    assert 'a „Új kapcsolatok” történetszál' not in w2.fallback_description
+    l = legendary_event_packet(event_name="Fekete Korona", access_context="ritka meghívás után indult", phase_label="végjáték", host_resolution="részsiker", legacy_note="az ügy neve megmaradt a városi történetekben")
+    assert "részsiker lezárást kapott" not in l.fallback_description.casefold()
+
+
+def test_extra_output_field_rejected():
+    with pytest.raises(AIDirectorGameMasterValidationError):
+        validate_game_master_surface(big(), {"title": "A trezor", "description": "A Belvárosi trezor részsikerrel zárult.", "branch": "escape"})
+
+
+def test_missing_grounding_anchor_rejected():
+    with pytest.raises(AIDirectorGameMasterValidationError):
+        validate_game_master_surface(big(), {"title": "Egy régi ügy", "description": "A csapat története részsikerrel zárult."})
+
+
+def test_valid_surface_is_accepted():
+    title, description = validate_game_master_surface(big(), {
+        "title": "A Belvárosi trezor visszhangja",
+        "description": "A Belvárosi trezor akció részsikerrel zárult, és a csapat szétszóródva jutott ki.",
+    })
+    assert title.startswith("A Belvárosi trezor")
+    assert "részsiker" in description
+
+
+def test_deterministic_fallback_source_and_digest_stable():
+    a = fallback_game_master_surface(big())
+    b = fallback_game_master_surface(big())
+    assert a.source == "deterministic_scenario_v2_fallback"
+    assert a.packet_digest == b.packet_digest
+
+
+def test_service_default_off_and_wrong_guild_never_calls_provider():
+    provider = FakeProvider()
+    gm = AIDirectorGameMaster(provider=provider, enabled=False, test_guild_id=10)
+    assert run(gm.surface(10, big())) is None
+    gm = AIDirectorGameMaster(provider=provider, enabled=True, test_guild_id=10)
+    assert run(gm.surface(11, big())) is None
+    assert provider.calls == 0
+
+
+def test_service_without_provider_fails_closed_to_deterministic_surface():
+    gm = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=10)
+    result = run(gm.surface(10, big()))
+    assert result and result.source == "deterministic_scenario_v2_fallback"
+
+
+def test_service_accepts_valid_provider_surface():
+    gm = AIDirectorGameMaster(provider=FakeProvider(), enabled=True, test_guild_id=10)
+    result = run(gm.surface(10, big()))
+    assert result and result.source == "ai_game_master"
+
+
+def test_service_provider_failure_never_loses_surface():
+    gm = AIDirectorGameMaster(provider=FakeProvider(error=RuntimeError("down")), enabled=True, test_guild_id=10)
+    result = run(gm.surface(10, big()))
+    assert result and result.source == "deterministic_scenario_v2_fallback"
+
+
+def test_service_invalid_provider_output_falls_back():
+    provider = FakeProvider({"title": "A Belvárosi trezor", "description": "A Belvárosi trezor után biztosan nyersz jutalmat."})
+    gm = AIDirectorGameMaster(provider=provider, enabled=True, test_guild_id=10)
+    result = run(gm.surface(10, big()))
+    assert result and result.source == "deterministic_scenario_v2_fallback"
+
+
+def test_provider_prompt_is_host_fact_only_and_authority_denying():
+    prompt = GroqAIDirectorGameMasterProvider.system_prompt().casefold()
+    user = GroqAIDirectorGameMasterProvider.user_prompt(big()).casefold()
+    assert "host_facts" in user
+    assert "nem dönthetsz" in prompt
+    assert "branch" in prompt
+    assert "jutalom" in prompt
+    assert "title és description" in prompt
+
+
+def test_provider_schema_is_strict_title_description_only():
+    schema = GroqAIDirectorGameMasterProvider.output_schema()
+    assert schema["additionalProperties"] is False
+    assert set(schema["properties"]) == {"title", "description"}
+
+
+def test_w22_5_does_not_modify_authoritative_domain_services():
+    layer = "\n".join(Path(path).read_text(encoding="utf-8") for path in (
+        "app/ai_director_game_master.py", "app/services/ai_director_game_master.py", "app/providers/ai_director_game_master_groq.py"
+    ))
+    for forbidden in ("services.economy", "services.heist", "services.chapters", "services.world", "services.memory", "services.assets", "services.contracts"):
+        assert forbidden not in layer
+
+
+def test_review_harness_is_non_player_and_declares_no_authority():
+    text = Path("scripts/ai_director_tier3_game_master_review.py").read_text(encoding="utf-8")
+    assert "player_facing_ai\": False" in text
+    assert "gameplay_authority\": \"NONE\"" in text
+    assert "live_deploy\": False" in text
+    assert "await asyncio.sleep(2.0)" in text
+
+
+def test_review_harness_gates_effective_surface_not_ai_ratio():
+    text = Path("scripts/ai_director_tier3_game_master_review.py").read_text(encoding="utf-8")
+    assert 'effective_validated = sum' in text
+    assert 'status = "PENDING_HUMAN" if effective_validated == len(rows)' in text
+    assert 'return 0 if effective_validated == len(rows)' in text
+
+
+def test_review_harness_reports_effective_validation_count():
+    text = Path("scripts/ai_director_tier3_game_master_review.py").read_text(encoding="utf-8")
+    assert 'EFFECTIVE_VALIDATED={effective_validated}' in text
+    assert '"effective_validated": effective_validated' in text
