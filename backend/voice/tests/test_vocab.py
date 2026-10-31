import json

from app.support_brain import OUTCOME_BY_PREFIX, outcome_for
from app.support_tools import PERSONAL, SUPPORT_TOOL_SCHEMAS
from app.vocab import Outcome, RefPrefix, SupportTool
from eval import run_scenarios

SCHEMA_NAMES = [s["function"]["name"] for s in SUPPORT_TOOL_SCHEMAS]


def test_every_support_tool_has_a_schema_and_every_schema_is_a_support_tool():
    assert sorted(SCHEMA_NAMES) == sorted(t.value for t in SupportTool)
    assert len(SCHEMA_NAMES) == len(set(SCHEMA_NAMES))


def test_schema_names_are_plain_strings():
    assert all(type(n) is str for n in SCHEMA_NAMES)


def test_personal_sets_name_real_tools():
    assert PERSONAL <= set(SupportTool)
    assert run_scenarios.PERSONAL <= PERSONAL


def test_outcomes_match_the_spring_contract():
    assert [o.value for o in Outcome] == ["RESOLVED", "TICKET_CREATED", "COMPLAINT_REGISTERED", "ROUTED", "ESCALATED", "ABANDONED"]


def test_harness_and_brain_use_the_same_reference_prefixes():
    brain = {prefix for prefix, _ in OUTCOME_BY_PREFIX}
    assert set(run_scenarios.PREFIX.values()) == brain == set(RefPrefix)
    assert {p.value for p in RefPrefix} == {"SR-", "CMP-", "RQ-", "ESC-"}


def test_enum_values_serialise_byte_identical():
    assert json.dumps({"outcome": outcome_for(["CMP-1"])}) == '{"outcome": "COMPLAINT_REGISTERED"}'
    assert json.dumps({"outcome": outcome_for([])}) == '{"outcome": "RESOLVED"}'
    assert f"{RefPrefix.SERVICE_REQUEST}40102" == "SR-40102"
