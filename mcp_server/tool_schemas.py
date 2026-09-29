"""Shared argument constraints; MCP server owns tool names and descriptions."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field

SearchQuery = Annotated[str, Field(min_length=1, max_length=300)]
SearchLimit = Annotated[int, Field(ge=1, le=5)]
SectionIdentifier = Annotated[str, Field(min_length=1, max_length=80)]
DEFAULT_SEARCH_LIMIT = 5


class ToolArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class SearchArguments(ToolArguments):
    query: SearchQuery
    limit: SearchLimit = DEFAULT_SEARCH_LIMIT


class SectionArguments(ToolArguments):
    document_id: SectionIdentifier
    section_id: SectionIdentifier
