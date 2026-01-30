"""Pydantic models for relationship discovery tools (Layer 2).

Based on PRD Section 6.2.
"""

from pydantic import BaseModel, Field

# === Get Foreign Keys ===


class GetForeignKeysInput(BaseModel):
    """Input for get_foreign_keys tool."""

    table_name: str = Field(description="Name of the table")
    schema_name: str = Field(
        default="public",
        description="Schema containing the table",
    )


class ForeignKeyRelation(BaseModel):
    """A single foreign key relationship."""

    constraint_name: str
    from_schema: str
    from_table: str
    from_columns: list[str]
    to_schema: str
    to_table: str
    to_columns: list[str]
    on_update: str
    on_delete: str


class GetForeignKeysOutput(BaseModel):
    """Output for get_foreign_keys tool."""

    table_name: str
    schema_name: str
    outgoing: list[ForeignKeyRelation] = Field(
        description="Tables this table references (this table has the FK column)"
    )
    incoming: list[ForeignKeyRelation] = Field(
        description="Tables that reference this table (other tables have FK to this)"
    )
    outgoing_count: int
    incoming_count: int


# === Find Join Path ===


class FindJoinPathInput(BaseModel):
    """Input for find_join_path tool."""

    from_table: str = Field(description="Starting table name")
    to_table: str = Field(description="Target table name")
    from_schema: str = Field(default="public", description="Schema of starting table")
    to_schema: str = Field(default="public", description="Schema of target table")
    max_depth: int = Field(
        default=4,
        ge=1,
        le=6,
        description="Maximum number of joins to traverse",
    )


class JoinStep(BaseModel):
    """A single step in a join path."""

    from_table: str
    from_schema: str
    from_column: str
    to_table: str
    to_schema: str
    to_column: str
    join_type: str = Field(description="Suggested join type based on FK direction")
    constraint_name: str


class JoinPath(BaseModel):
    """A complete path between two tables."""

    steps: list[JoinStep]
    depth: int
    sql_example: str = Field(description="Example JOIN clause for this path")


class FindJoinPathOutput(BaseModel):
    """Output for find_join_path tool."""

    from_table: str
    to_table: str
    paths: list[JoinPath]
    paths_found: int
    note: str | None = Field(
        default=None,
        description="Additional context (e.g., 'multiple paths found, showing shortest')",
    )
