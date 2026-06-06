"""Tests for service runner key validation (T0.1.2)."""

import importlib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bridge.services.runner import SERVICE_MAP, SERVICE_ALIASES, _resolve_service_name

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _extract_plist_service_names() -> list[tuple[str, str]]:
    """Parse all agent plist files and extract the service name argument."""
    names = []
    for plist_path in SCRIPTS_DIR.glob("com.bumba.agent-*.plist"):
        # Skip monitor and other non-service plists
        if "bridge" in plist_path.name or "monitor" in plist_path.name:
            continue
        try:
            # Test-only code parsing repo-controlled plist files; no untrusted XML.
            # Sprint 08.03 (#781). Revisit 2026-09-01.
            tree = ET.parse(plist_path)  # nosemgrep: python.lang.security.use-defused-xml-parse.use-defused-xml-parse
            root = tree.getroot()
            dict_elem = root.find("dict")
            if dict_elem is None:
                continue
            elements = list(dict_elem)
            for i, elem in enumerate(elements):
                if elem.tag == "key" and elem.text == "ProgramArguments":
                    array = elements[i + 1]
                    strings = [s.text for s in array.findall("string") if s.text]
                    # Service name is the last argument
                    for j, s in enumerate(strings):
                        if "bridge.services.runner" in s and j + 1 < len(strings):
                            names.append((plist_path.name, strings[j + 1]))
        except ET.ParseError:
            continue
    return names


class TestServiceRunnerKeys:
    def test_service_map_not_empty(self):
        """SERVICE_MAP should have entries."""
        assert len(SERVICE_MAP) >= 7

    def test_service_map_has_valid_imports(self):
        """Every SERVICE_MAP entry should reference an importable module."""
        for name, (module_path, class_name) in SERVICE_MAP.items():
            try:
                mod = importlib.import_module(module_path)
                assert hasattr(mod, class_name), (
                    f"Service '{name}': {module_path} has no class '{class_name}'"
                )
            except ImportError as e:
                pytest.fail(f"Service '{name}': cannot import {module_path}: {e}")

    def test_aliases_resolve_to_valid_services(self):
        """Every alias should resolve to a valid SERVICE_MAP key."""
        for alias, target in SERVICE_ALIASES.items():
            assert target in SERVICE_MAP, (
                f"Alias '{alias}' points to '{target}' which is not in SERVICE_MAP"
            )

    def test_resolve_direct_name(self):
        """Direct service names should resolve to themselves."""
        assert _resolve_service_name("briefing") == "briefing"
        assert _resolve_service_name("job_search") == "job_search"

    def test_resolve_alias(self):
        """Aliases should resolve to their target."""
        assert _resolve_service_name("knowledge-review") == "knowledge_review"
        assert _resolve_service_name("job-search") == "job_search"
        assert _resolve_service_name("job-execute") == "job_search_execute"

    def test_resolve_unknown_passthrough(self):
        """Unknown names should pass through (run_service will raise)."""
        assert _resolve_service_name("nonexistent") == "nonexistent"


class TestPlistServiceNames:
    """Test that plist files reference valid service names."""

    def test_plist_files_exist(self):
        """At least some plist files should exist in scripts/."""
        plists = list(SCRIPTS_DIR.glob("com.bumba.agent-*.plist"))
        # Skip if scripts dir doesn't have plists (dev environment)
        if not plists:
            pytest.skip("No plist files found in scripts/")

    def test_all_plist_services_in_service_map(self):
        """Every plist service name must exist in SERVICE_MAP."""
        plist_services = _extract_plist_service_names()
        if not plist_services:
            pytest.skip("No plist service names extracted")
        for plist_name, service_name in plist_services:
            resolved = _resolve_service_name(service_name)
            assert resolved in SERVICE_MAP, (
                f"Plist {plist_name} uses service name '{service_name}' "
                f"(resolved: '{resolved}') which is not in SERVICE_MAP. "
                f"Available: {list(SERVICE_MAP.keys())}"
            )
