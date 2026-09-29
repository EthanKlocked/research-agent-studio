from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Text = Annotated[str, Field(min_length=1, max_length=2500)]
Short = Annotated[str, Field(min_length=1, max_length=300)]

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class RunRequest(Strict):
    question: Annotated[str, Field(min_length=1, max_length=2000)]
    mode: Literal["live", "test"] = "live"
    scenario: Literal["pass", "revise", "limit", "empty", "tool_error", "timeout"] = "pass"

    @field_validator("question")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip()

class Interpretation(Strict):
    interpreted_request: Text

class Plan(Strict):
    plan: Annotated[list[Short], Field(min_length=1, max_length=6)]

class ResearchResult(Strict):
    summary: Text

class Claim(Strict):
    text: Text
    citation_ids: Annotated[list[Short], Field(min_length=1, max_length=6)]

class Report(Strict):
    title: Short
    summary: Text
    claims: Annotated[list[Claim], Field(min_length=1, max_length=8)]
    limitations: Annotated[list[Short], Field(max_length=8)]

class Evaluation(Strict):
    decision: Literal["pass", "revise"]
    issues: Annotated[list[Short], Field(max_length=6)]
    follow_up: Annotated[list[Short], Field(max_length=6)]

ROLE_SCHEMAS = {"Listener": Interpretation, "Planner": Plan, "Researcher": ResearchResult, "Reporter": Report, "Evaluator": Evaluation}

def validate_citations(report, evidence):
    ids = {e["id"] for e in evidence}
    if any(not set(c["citation_ids"]).issubset(ids) for c in report["claims"]):
        raise ValueError("Unknown citation ID")
