"""Copertura pura-stdlib: lo Swagger e il gateway devono restare 1:1."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWAGGER = json.loads((ROOT / "swagger.json").read_text(encoding="utf-8"))
CATALOG = json.loads((ROOT / "app/api/v3/upstream_catalog.json").read_text(encoding="utf-8"))
METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}


class CatalogCoverageTests(unittest.TestCase):
    def test_all_swagger_operations_are_exposed_once(self):
        expected = {
            (method.upper(), path)
            for path, item in SWAGGER["paths"].items()
            for method in item
            if method.lower() in METHODS
        }
        actual = {(op["method"], op["path"]) for op in CATALOG["operations"]}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(CATALOG["operations"]))
        self.assertEqual(len(actual), 91)

    def test_all_eight_namespaces_are_present(self):
        self.assertEqual(
            {op["tag"] for op in CATALOG["operations"]},
            {"Access", "Badges", "Bus", "Eating", "GAUniparthenope",
             "Notifications", "Reports", "UniparthenopeApp"})

    def test_critical_operations_are_not_missing(self):
        actual = {(op["method"], op["path"]) for op in CATALOG["operations"]}
        for operation in {
            ("GET", "/UniparthenopeApp/v1/general/image/{personId}"),
            ("GET", "/UniparthenopeApp/v1/general/image_prof/{idAb}"),
            ("POST", "/Badges/v3/checkQrCode"),
            ("GET", "/Badges/v1/generateQrCode"),
            ("POST", "/Notifications/v1/registerDevice"),
            ("GET", "/Bus/v1/bus/{sede}"),
            ("GET", "/Eating/v1/getAllToday"),
            ("POST", "/UniparthenopeApp/v1/students/bookExam/{cdsId}/{adId}/{appId}"),
        }:
            self.assertIn(operation, actual)

    def test_security_is_copied_from_swagger(self):
        expected = {}
        for path, item in SWAGGER["paths"].items():
            for method, definition in item.items():
                if method.lower() in METHODS:
                    expected[(method.upper(), path)] = bool(definition.get("security"))
        actual = {(op["method"], op["path"]): op["protected"]
                  for op in CATALOG["operations"]}
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
