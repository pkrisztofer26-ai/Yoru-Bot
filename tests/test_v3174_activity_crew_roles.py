from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ActivityMilestonePersistenceTests(unittest.TestCase):
    def test_activity_layout_is_db_persisted_not_file_only(self) -> None:
        cfg = (ROOT / "app" / "activity_config.py").read_text(encoding="utf-8")
        service = (ROOT / "app" / "services" / "activity.py").read_text(encoding="utf-8")
        self.assertIn('ACTIVITY_MILESTONE_LAYOUT_KEY = "activity_milestone_layout"', cfg)
        self.assertIn("ACTIVITY_MILESTONE_LAYOUT_VERSION =", cfg)
        self.assertIn("get_milestone_layout", service)
        self.assertIn("set_list(guild_id, cfg.ACTIVITY_MILESTONE_LAYOUT_KEY", service)

    def test_final_rank_names_exist(self) -> None:
        cfg = (ROOT / "app" / "activity_config.py").read_text(encoding="utf-8")
        for name in (
            "Csöves", "Pórnép", "Közmunkás", "Minimálbéres", "Melós",
            "Szakmunkás", "Maszekos", "Kft.-tulaj", "Vállalkozó",
            "Nagyvállalkozó", "Újgazdag", "Stróman", "Oligarcha",
            "Felső tízezer", "NER-elit",
        ):
            self.assertIn(name, cfg)


class CrewDiscordRoleRegressionTests(unittest.TestCase):
    def test_crew_role_id_is_persisted(self) -> None:
        db = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        self.assertIn("discord_role_id INTEGER", db)
        self.assertIn("ALTER TABLE crews ADD COLUMN discord_role_id INTEGER", db)
        self.assertIn("set_crew_discord_role_id", db)

    def test_crew_role_is_hoisted_and_membership_synced(self) -> None:
        service = (ROOT / "app" / "services" / "crew.py").read_text(encoding="utf-8")
        self.assertIn("hoist=True", service)
        self.assertIn("await member.add_roles(role", service)
        self.assertGreaterEqual(service.count("await self._sync_member_discord_role(membership)"), 2)
        self.assertIn("await member.remove_roles(role", service)
        self.assertIn("await role.delete", service)

    def test_existing_crews_are_repaired_on_ready(self) -> None:
        cog = (ROOT / "app" / "cogs" / "crew.py").read_text(encoding="utf-8")
        main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("reconcile_discord_roles", cog)
        self.assertIn("self.crew.bind_bot(self)", main)


if __name__ == "__main__":
    unittest.main()
