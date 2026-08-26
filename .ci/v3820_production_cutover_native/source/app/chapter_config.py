from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChapterStageDefinition:
    key: str
    title: str
    summary: str
    start_day: int


@dataclass(frozen=True, slots=True)
class ChapterEndingDefinition:
    key: str
    title: str
    summary: str


@dataclass(frozen=True, slots=True)
class ChapterDefinition:
    key: str
    emoji: str
    title: str
    opening: str
    duration_days: int
    stages: tuple[ChapterStageDefinition, ...]
    endings: tuple[ChapterEndingDefinition, ...]

    def stage(self, key: str) -> ChapterStageDefinition | None:
        return next((item for item in self.stages if item.key == key), None)


# W21.1 foundation pilot. The chapter is a server-level orchestration shell only:
# gameplay outcomes continue to belong to Scenario, World, Community Project,
# Contract, Business/Crime/Social and Asset Provenance authorities.
PILOT_CHAPTER_KEY = "fault_lines"

CHAPTERS: tuple[ChapterDefinition, ...] = (
    ChapterDefinition(
        key=PILOT_CHAPTER_KEY,
        emoji="📖",
        title="Törésvonalak",
        opening=(
            "Több, eddig különálló országos feszültség kezd ugyanabba az irányba mutatni. "
            "A következő hetekben nem egyetlen parancs, hanem a szerver valódi döntései alakítják, mi marad utánuk."
        ),
        duration_days=21,
        stages=(
            ChapterStageDefinition(
                "omens", "Jelek a háttérben",
                "A világhelyzet, a helyi ügyek és a közösségi aktivitás még csak különálló jeleknek tűnnek.", 0,
            ),
            ChapterStageDefinition(
                "pressure", "Növekvő nyomás",
                "A különálló ügyek összeérnek; a business, crime, social és community reakciók egyre többet számítanak.", 7,
            ),
            ChapterStageDefinition(
                "turning_point", "Fordulópont",
                "A szerver addigi története már kirajzol több lehetséges lezárást, de az ending még nincs eldöntve.", 14,
            ),
        ),
        endings=(
            ChapterEndingDefinition(
                "shared_recovery", "Közös rendeződés",
                "A közösségi és legitim válaszok domináns örökséget hagynak a világban.",
            ),
            ChapterEndingDefinition(
                "fractured_balance", "Törékeny egyensúly",
                "Egyik oldal sem uralja teljesen a történetet; a világ kompromisszumokkal lép tovább.",
            ),
            ChapterEndingDefinition(
                "shadow_network", "Árnyékhálózat",
                "Az illegális és zárt körű utak erősebb történeti nyomot hagynak a fejezet végén.",
            ),
        ),
    ),
)

CHAPTER_BY_KEY = {item.key: item for item in CHAPTERS}
