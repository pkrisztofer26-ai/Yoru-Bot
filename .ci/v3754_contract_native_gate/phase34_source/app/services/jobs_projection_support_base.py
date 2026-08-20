from __future__ import annotations
import json
import logging
import random
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from app import db_backend as aiosqlite
from app import jobs_config as cfg
from app.job_framework import DecisionScenario, GridGame, PerformanceRating, RiskCashout, ScenarioChoice, SequenceGame, clamp_score
from app.services.server_settings import ServerSettingsService
from app.services.gameplay_settings import GameplaySettingsService
from app.services.characters import CharacterService
from app.services.training import TrainingService
from app.services.vehicles import VehicleService
from app.services.housing import HousingService
from app.services.memory_adapters import MemoryAdapterService
from app.scenarios.adapters import definition_from_legacy
from app.scenarios.config import SCENARIO_V2_ENABLED_KEY
from app.scenarios.engine import ScenarioEngine
from app.scenarios.models import ScenarioContext, ScenarioDefinition
from app import housing_config as housing_cfg
from app.text_hu import format_hu_relative
log = logging.getLogger('vaultbot.jobs')

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _now() -> str:
    return _utcnow().isoformat()

def _format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f'{hours} óra')
    if minutes:
        parts.append(f'{minutes} perc')
    if not parts:
        parts.append(f'{max(1, secs)} mp')
    return ' '.join(parts)

class JobBusyError(ValueError):
    pass

class JobCooldownError(ValueError):

    def __init__(self, job: str, remaining_seconds: float, *, abandoned: bool=False) -> None:
        self.job = job
        self.remaining_seconds = max(0.0, float(remaining_seconds))
        self.available_at = _utcnow() + timedelta(seconds=self.remaining_seconds)
        self.abandoned = bool(abandoned)
        if job == 'borsod':
            if abandoned:
                message = f'Az előző próbálkozás félbemaradt. Újra próbálkozhatsz: {format_hu_relative(self.available_at)}.'
            else:
                message = f'Még nem próbálkozhatsz újra. Újra elérhető: {format_hu_relative(self.available_at)}.'
        elif abandoned:
            message = f'Az előző műszak félbemaradt. Új műszak: {format_hu_relative(self.available_at)}.'
        else:
            message = f'Még nem vállalhatsz új műszakot. Újra elérhető: {format_hu_relative(self.available_at)}.'
        super().__init__(message)

@dataclass(frozen=True, slots=True)
class JobResult:
    session_id: str
    job: str
    base_reward: int
    reward: int
    score: int
    rating: str
    mastery_xp: int
    mastery_level: int
    wallet: int
    world_note: str | None = None
WAREHOUSE_TOKENS = ('A12', 'C04', 'B17', 'A08', 'D03', 'F11', 'C19', 'B02', 'E07', 'A21', 'D14', 'F05')
BORSOD_LOOT = (('🔩', 42000, 20), ('🔌', 93000, 15), ('📺', 117000, 10), ('🚲', 158000, 6), ('💵', 138000, 9), ('📦', 248000, 3), ('🗑️', 6000, 25), ('🧯', 27000, 12))
COURIER_ASSIGNMENTS = ('Csomag a vasútállomásra', 'Sürgős gyógyszercsomag', 'Utánvétes műszaki cucc', 'Két cím egy utcában', 'Elírt házszámos csomag', 'Törékeny küldemény', 'Utolsó perces expressz', 'Nagy csomag a negyedikre')
TAXI_PASSENGERS = ('Pista bácsi → Vasútállomás', 'Éjszakás melós → Ipari park', 'Késésben lévő utas → Buszpályaudvar', 'Két bőrönd → Belváros', 'Morgós utas → Kórház', 'Turista → Vár', 'Sietős diák → Egyetem')
ROUTES = {'safe': {'base': (52000, 78000), 'score': (2, 10), 'risk_penalty': 0.01}, 'long': {'base': (68000, 112000), 'score': (-1, 10), 'risk_penalty': 0.05}, 'risky': {'base': (84000, 142000), 'score': (-6, 12), 'risk_penalty': 0.1}}
ROUTE_CHOICES = {'safe': {'label': 'Főút', 'emoji': '🛣️'}, 'long': {'label': 'Külső út', 'emoji': '↗️'}, 'risky': {'label': 'Mellékutcák', 'emoji': '🏙️'}}
ROUTE_PROFILE_CLUES = {'safe': ('Sűrűbbnek látszik a forgalom, de az út jól ismert.', 'Több lámpa van rajta, viszont nincs friss akadályjelzés.', 'A navigáció stabil menetidőt mutat, de most kezd nőni a forgalom.'), 'long': ('Hosszabbnak tűnik, viszont egyenletesebb lehet a tempó.', 'A térkép kevés torlódást mutat, de kerülőt tesz hozzá.', 'Nagyobb ívet ír le, cserébe kevesebb kereszteződés van rajta.'), 'risky': ('Rövidebbnek mutatja a térkép, de nincs róla friss forgalmi adat.', 'Közvetlenebb út, viszont két utcánál útmunka-jelzés látszik.', 'Papíron gyors, de keskenyebb szakaszokon visz át.')}
WAREHOUSE_TWISTS = ({'text': 'Normál raklap érkezett.', 'length': 4}, {'text': 'A műszakvezető rád dobott egy sürgős raklapot — eggyel több címkét kell fejben tartanod.', 'length': 5}, {'text': 'A szkenner kihagy egy sort, ezért most rövidebb, de szokatlan sorrend jön.', 'length': 3}, {'text': 'Két raklap címkéit összekeverték — hosszabb sorrendet kapsz.', 'length': 5}, {'text': 'Áruátvétel közben megváltozott a prioritás — új sorrend érkezik.', 'length': 4})

def _choice(key: str, label: str, emoji: str, *, description: str='', chance: float=1.0, reward_success: float=1.0, reward_fail: float=0.65, score_success: int=0, score_fail: int=-8, continue_success: bool=True, continue_fail: bool=True, default: bool=False) -> ScenarioChoice:
    return ScenarioChoice(key=key, label=label, emoji=emoji, description=description, success_chance=chance, reward_success=reward_success, reward_fail=reward_fail, score_success=score_success, score_fail=score_fail, continue_on_success=continue_success, continue_on_fail=continue_fail, default=default)
