from __future__ import annotations

from dataclasses import dataclass

BETTING_ENABLED_KEY = "betting_enabled"
BETTING_TIPPMIX_ENABLED_KEY = "betting_tippmix_enabled"
BETTING_HORSE_ENABLED_KEY = "betting_horse_enabled"
BETTING_DM_ENABLED_KEY = "betting_dm_enabled"
BETTING_CHANNEL_KEY = "betting_channel_id"
BETTING_LOG_CHANNEL_KEY = "betting_log_channel_id"
BETTING_RESULTS_FORUM_KEY = "betting_results_forum_id"
BETTING_RESULTS_THREAD_ID_KEY = "betting_results_thread_id"
BETTING_RESULTS_THREAD_DAY_KEY = "betting_results_thread_day"
BETTING_MIN_STAKE_KEY = "betting_min_stake"
BETTING_MAX_LEGS_KEY = "betting_max_legs"
BETTING_MAX_PAYOUT_KEY = "betting_max_payout"
BETTING_DAILY_MATCHES_KEY = "betting_daily_matches"
BETTING_HORSE_INTERVAL_KEY = "betting_horse_interval_hours"
BETTING_HORSE_CLOSE_MINUTES_KEY = "betting_horse_close_minutes"

DEFAULT_MIN_STAKE = 50_000
DEFAULT_MAX_LEGS = 12
DEFAULT_MAX_PAYOUT = 50_000_000_000
DEFAULT_DAILY_MATCHES = 32
DEFAULT_HORSE_INTERVAL_HOURS = 4
DEFAULT_HORSE_CLOSE_MINUTES = 2
MAX_DAILY_MATCHES = 60
MIN_DAILY_MATCHES = 12


@dataclass(frozen=True, slots=True)
class Team:
    name: str
    rating: int


def _t(name: str, rating: int) -> Team:
    return Team(name, rating)


# A Yoru Tippmix virtuális adatbázisa. Nem valódi menetrend/odds API: a klubnevek
# a napi fiktív meccskínálat alapját adják, így a rendszer külső szolgáltatás nélkül
# stabilan működik. Magyarországnál szándékosan szélesebb a klubpool, nem csak NB I.
LEAGUES: dict[str, tuple[Team, ...]] = {
    "🇭🇺 Magyarország": (
        _t("Ferencvárosi TC", 86), _t("Paksi FC", 78), _t("Puskás Akadémia", 79), _t("Diósgyőri VTK", 73),
        _t("Újpest FC", 74), _t("Debreceni VSC", 74), _t("MTK Budapest", 73), _t("Zalaegerszegi TE", 71),
        _t("Fehérvár FC", 72), _t("Kecskeméti TE", 70), _t("Nyíregyháza Spartacus", 69), _t("ETO FC Győr", 72),
        _t("Vasas FC", 72), _t("Budapest Honvéd", 70), _t("Szeged-Csanád GA", 68), _t("Gyirmót FC Győr", 67),
        _t("Soroksár SC", 65), _t("Kozármisleny", 65), _t("BVSC-Zugló", 64), _t("Mezőkövesd Zsóry FC", 68),
        _t("Budafoki MTE", 64), _t("FC Ajka", 63), _t("Kazincbarcikai SC", 65), _t("Szentlőrinc SE", 62),
        _t("Békéscsaba 1912 Előre", 62), _t("Tatabányai SC", 61), _t("Kisvárda FC", 70), _t("Csákvári TK", 63),
        _t("Tiszakécskei LC", 61), _t("Mosonmagyaróvári TE", 59), _t("Haladás", 64), _t("Pécsi MFC", 64),
        _t("III. Kerületi TVE", 59), _t("Dorogi FC", 58), _t("Budaörsi SC", 59), _t("Veszprém FC", 60),
        _t("Kaposvári Rákóczi", 60), _t("Siófok", 60), _t("Eger SE", 57), _t("Putnok FC", 57),
    ),
    "🏴 Premier League": (
        _t("Arsenal", 91), _t("Manchester City", 92), _t("Liverpool", 91), _t("Chelsea", 86), _t("Manchester United", 84),
        _t("Tottenham", 84), _t("Newcastle United", 85), _t("Aston Villa", 83), _t("Brighton", 79), _t("West Ham", 78),
        _t("Crystal Palace", 79), _t("Fulham", 77), _t("Brentford", 77), _t("Everton", 75), _t("Wolves", 75),
        _t("Nottingham Forest", 77), _t("Bournemouth", 77), _t("Leeds United", 74), _t("Burnley", 72), _t("Sunderland", 72),
    ),
    "🇪🇸 La Liga": (
        _t("Real Madrid", 94), _t("Barcelona", 93), _t("Atlético Madrid", 88), _t("Athletic Club", 84), _t("Villarreal", 82),
        _t("Real Betis", 80), _t("Real Sociedad", 80), _t("Sevilla", 77), _t("Valencia", 76), _t("Girona", 79),
        _t("Celta Vigo", 75), _t("Osasuna", 74), _t("Mallorca", 73), _t("Getafe", 72), _t("Rayo Vallecano", 73),
        _t("Espanyol", 72), _t("Alavés", 71), _t("Levante", 69), _t("Elche", 69), _t("Real Oviedo", 68),
    ),
    "🇩🇪 Bundesliga": (
        _t("Bayern München", 93), _t("Bayer Leverkusen", 90), _t("Borussia Dortmund", 87), _t("RB Leipzig", 85),
        _t("Eintracht Frankfurt", 82), _t("Stuttgart", 81), _t("Freiburg", 78), _t("Wolfsburg", 77), _t("Mainz", 77),
        _t("Werder Bremen", 75), _t("Hoffenheim", 75), _t("Borussia Mönchengladbach", 76), _t("Union Berlin", 74),
        _t("Augsburg", 73), _t("St. Pauli", 71), _t("Heidenheim", 70), _t("Hamburg", 73), _t("Köln", 72),
    ),
    "🇮🇹 Serie A": (
        _t("Inter", 91), _t("Napoli", 89), _t("Juventus", 87), _t("AC Milan", 87), _t("Atalanta", 86), _t("Roma", 84),
        _t("Lazio", 82), _t("Fiorentina", 81), _t("Bologna", 80), _t("Torino", 76), _t("Como", 76), _t("Genoa", 74),
        _t("Udinese", 73), _t("Parma", 72), _t("Cagliari", 71), _t("Lecce", 70), _t("Verona", 69), _t("Sassuolo", 72),
        _t("Pisa", 68), _t("Cremonese", 68),
    ),
    "🇫🇷 Ligue 1": (
        _t("Paris Saint-Germain", 94), _t("Marseille", 85), _t("Monaco", 84), _t("Lille", 82), _t("Lyon", 81), _t("Nice", 80),
        _t("Lens", 79), _t("Strasbourg", 76), _t("Rennes", 77), _t("Toulouse", 73), _t("Auxerre", 70), _t("Nantes", 70),
        _t("Brest", 75), _t("Reims", 72), _t("Le Havre", 68), _t("Lorient", 69), _t("Paris FC", 70), _t("Metz", 67),
    ),
    "🇵🇹 Primeira Liga": (
        _t("Sporting CP", 87), _t("Benfica", 87), _t("Porto", 86), _t("Braga", 81), _t("Vitória Guimarães", 77),
        _t("Famalicão", 73), _t("Casa Pia", 71), _t("Estoril", 71), _t("Boavista", 69), _t("Rio Ave", 70),
        _t("Moreirense", 71), _t("Gil Vicente", 69), _t("Arouca", 69), _t("Santa Clara", 70), _t("Nacional", 68),
        _t("Farense", 66), _t("AVS", 66), _t("Alverca", 65),
    ),
    "🌍 Európai kupák": (
        _t("Real Madrid", 94), _t("Barcelona", 93), _t("Paris Saint-Germain", 94), _t("Bayern München", 93), _t("Manchester City", 92),
        _t("Liverpool", 91), _t("Arsenal", 91), _t("Inter", 91), _t("Bayer Leverkusen", 90), _t("Napoli", 89),
        _t("Atlético Madrid", 88), _t("Benfica", 87), _t("Sporting CP", 87), _t("Borussia Dortmund", 87), _t("Juventus", 87),
        _t("AC Milan", 87), _t("Atalanta", 86), _t("Chelsea", 86), _t("Porto", 86), _t("Marseille", 85),
        _t("RB Leipzig", 85), _t("Newcastle United", 85), _t("Monaco", 84), _t("Roma", 84), _t("Ferencvárosi TC", 82),
    ),
}

HORSE_NAMES = (
    "Kincsem Árnyéka", "Borsodi Betyár", "Aranypatkó", "Villám Vezér", "Tiszai Szél", "Pannon Csillag",
    "Fekete Gyémánt", "Hajnali Futár", "Tokaji Titán", "Rónák Királya", "Zempléni Zivatar", "Dunai Herceg",
    "Pesti Rakéta", "Alföldi Ász", "Bakonyi Vihar", "Mátrai Mágus",
)

MARKET_GROUP_LABELS = {
    "1x2": "1X2",
    "double": "Dupla esély",
    "goals": "Gólok",
    "btts": "Mindkét csapat gólt szerez",
    "dnb": "Döntetlen nélküli",
    "half": "Félidő",
    "handicap": "Handicap",
    "score": "Pontos eredmény",
}

# Kupa-poolok ugyanazokból a klubadatokból dolgoznak, de külön napi piacot kapnak.
# Így a panelben a liga- és kupameccsek ténylegesen külön böngészhetők.
LEAGUES["🏆 Magyar Kupa"] = LEAGUES["🇭🇺 Magyarország"]
LEAGUES["🏆 Angol kupák"] = LEAGUES["🏴 Premier League"]
LEAGUES["🏆 Copa del Rey"] = LEAGUES["🇪🇸 La Liga"]
LEAGUES["🏆 DFB-Pokal"] = LEAGUES["🇩🇪 Bundesliga"]
LEAGUES["🏆 Coppa Italia"] = LEAGUES["🇮🇹 Serie A"]
LEAGUES["🏆 Coupe de France"] = LEAGUES["🇫🇷 Ligue 1"]
