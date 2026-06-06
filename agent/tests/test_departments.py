"""Tests for MS4.9 + MS4.10: Department Registry."""

from __future__ import annotations


from bridge.departments import (
    DEPARTMENTS,
    detect_department,
    format_department_detail,
    format_departments_table,
    get_department,
    get_persona_for_task,
    list_departments,
)


# ── Registry ──

class TestDepartmentRegistry:
    def test_all_departments_present(self):
        assert "engineering" in DEPARTMENTS
        assert "data" in DEPARTMENTS
        assert "qa" in DEPARTMENTS
        assert "ops" in DEPARTMENTS

    def test_department_has_required_fields(self):
        for name, dept in DEPARTMENTS.items():
            assert dept.name == name
            assert dept.display_name
            assert dept.description
            assert dept.status in ("active", "inactive")
            assert isinstance(dept.skills, list)
            assert isinstance(dept.routing_keywords, list)

    def test_get_department(self):
        dept = get_department("data")
        assert dept is not None
        assert dept.display_name == "Data & Analytics"

    def test_get_department_case_insensitive(self):
        assert get_department("QA") is not None
        assert get_department("Ops") is not None

    def test_get_department_nonexistent(self):
        assert get_department("nonexistent") is None

    def test_list_departments(self):
        deps = list_departments()
        assert len(deps) == 4
        assert all(d.status == "active" for d in deps)


# ── Department Detection ──

class TestDepartmentDetection:
    def test_detect_data(self):
        assert detect_department("analyze the CSV data") == "data"

    def test_detect_qa(self):
        assert detect_department("write tests for the parser") == "qa"

    def test_detect_ops(self):
        assert detect_department("check disk usage and monitor health") == "ops"

    def test_detect_engineering(self):
        assert detect_department("implement a new class for parsing") == "engineering"

    def test_detect_none(self):
        assert detect_department("hello world") is None

    def test_detect_strongest_match(self):
        # "analyze data from csv" has 3 data keywords vs 0 for others
        assert detect_department("analyze data from csv chart") == "data"


# ── Persona Routing ──

class TestPersonaRouting:
    def test_data_persona(self):
        assert get_persona_for_task("analyze the metrics data") == "data-analyst"

    def test_qa_persona(self):
        assert get_persona_for_task("write tests for coverage") == "qa-engineer"

    def test_ops_persona(self):
        assert get_persona_for_task("check deployment health") == "ops-engineer"

    def test_engineering_no_persona(self):
        # Engineering uses default persona
        assert get_persona_for_task("implement a function") is None

    def test_unknown_no_persona(self):
        assert get_persona_for_task("random words") is None


# ── Formatting ──

class TestFormatting:
    def test_departments_table(self):
        table = format_departments_table()
        assert "Department" in table
        assert "Engineering" in table
        assert "Data & Analytics" in table
        assert "Quality Assurance" in table
        assert "Operations" in table

    def test_department_detail(self):
        detail = format_department_detail("data")
        assert detail is not None
        assert "Data & Analytics" in detail
        assert "data-analyst" in detail
        assert "data-analysis" in detail

    def test_department_detail_nonexistent(self):
        assert format_department_detail("nonexistent") is None

    def test_departments_table_has_all_rows(self):
        table = format_departments_table()
        # Header + separator + 4 departments = 6 lines
        lines = table.strip().split("\n")
        assert len(lines) == 6
