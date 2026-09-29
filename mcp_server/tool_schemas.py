"""Shared argument constraints; MCP server owns tool names and descriptions."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field

SearchQuery = Annotated[str, Field(min_length=1, max_length=300)]
SearchLimit = Annotated[int, Field(ge=1, le=5)]
SectionIdentifier = Annotated[str, Field(min_length=1, max_length=80)]
SourceIdentifier = Annotated[str, Field(pattern=r"^gw_[a-f0-9]{32}$", min_length=35, max_length=35)]
DEFAULT_SEARCH_LIMIT = 5


class ToolArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class SearchArguments(ToolArguments):
    query: SearchQuery
    limit: SearchLimit = DEFAULT_SEARCH_LIMIT


class SectionArguments(ToolArguments):
    document_id: SectionIdentifier
    section_id: SectionIdentifier


class PageArguments(ToolArguments):
    source_id: SourceIdentifier


ARGUMENT_SCHEMAS = {"search_documents": SearchArguments, "get_section": SectionArguments,
                    "web_search": SearchArguments, "read_page": PageArguments}
