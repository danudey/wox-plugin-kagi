import json
import pathlib
import unittest

from src.services import SERVICES
from src.settings import setting_keys

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestPluginManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        cls.definitions = cls.manifest["SettingDefinitions"]

    def declared_keys(self):
        return {item["Value"]["Key"] for item in self.definitions if "Key" in item["Value"]}

    def test_required_fields_are_present(self):
        for field in ("Id", "Name", "Description", "Author", "Version", "Runtime", "Entry", "Icon"):
            self.assertTrue(self.manifest.get(field), field)

        self.assertTrue(self.manifest["TriggerKeywords"])
        self.assertTrue(self.manifest["SupportedOS"])

    def test_every_setting_the_code_reads_is_declared(self):
        declared = self.declared_keys()

        for key in setting_keys():
            self.assertIn(key, declared)

    def test_no_orphan_settings_are_declared(self):
        self.assertEqual(self.declared_keys() - set(setting_keys()), set())

    def test_manifest_keyword_defaults_match_the_catalog(self):
        defaults = {item["Value"]["Key"]: item["Value"]["DefaultValue"] for item in self.definitions if item["Type"] == "textbox"}

        for service in SERVICES:
            self.assertEqual(defaults[f"service_{service.key}_keyword"], service.default_keyword, service.key)

    def test_paid_features_default_to_off(self):
        defaults = {item["Value"]["Key"]: item["Value"]["DefaultValue"] for item in self.definitions if item["Type"] == "checkbox"}

        for key in ("api_search_inline", "api_fastgpt_inline", "api_summarizer_inline"):
            self.assertEqual(defaults[key], "false", key)

    def test_every_icon_referenced_by_a_service_exists(self):
        for service in SERVICES:
            self.assertTrue((ROOT / service.icon).is_file(), service.icon)

        self.assertTrue((ROOT / self.manifest["Icon"].split(":", 1)[1]).is_file())

        for icon in ("icons/open.svg", "icons/copy.svg"):
            self.assertTrue((ROOT / icon).is_file(), icon)


if __name__ == "__main__":
    unittest.main()
