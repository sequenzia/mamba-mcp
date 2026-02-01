"""Pydantic models for relationship discovery tools (Layer 2).

Based on PRD Section 5.2, 9.2.
"""

from typing import Literal

from pydantic import BaseModel, Field

# === Get Foreign Keys ===


class GetForeignKeysInput(BaseModel):
    """Input for get_foreign_keys tool."""

    table_name: str = Field(description="Name of the table")
    schema_name: str = Field(
        description="Schema containing the table",
    )


class ForeignKeyInfo(BaseModel):
    """A single foreign key relationship with full details."""

    constraint_name: str = Field(description="Name of the FK constraint")
    source_schema: str = Field(description="Schema of the source (referencing) table")
    source_table: str = Field(description="Name of the source (referencing) table")
    source_columns: list[str] = Field(description="Columns in the source table")
    target_schema: str = Field(description="Schema of the target (referenced) table")
    target_table: str = Field(description="Name of the target (referenced) table")
    target_columns: list[str] = Field(description="Columns in the target table")
    delete_rule: str = Field(
        default="RESTRICT",
        description="Delete rule (CASCADE, RESTRICT, SET NULL, SET DEFAULT, NO ACTION)",
    )


class ForeignKeysOutput(BaseModel):
    """Output for get_foreign_keys tool."""

    table_name: str = Field(description="Name of the queried table")
    schema_name: str = Field(description="Schema of the queried table")
    outgoing: list[ForeignKeyInfo] = Field(
        default_factory=list,
        description="FKs where this table references others (outgoing relationships)",
    )
    incoming: list[ForeignKeyInfo] = Field(
        default_factory=list,
        description="FKs where other tables reference this table (incoming relationships)",
    )
    outgoing_count: int = Field(description="Number of outgoing foreign keys")
    incoming_count: int = Field(description="Number of incoming foreign keys")


# === Find Join Path ===


class FindJoinPathInput(BaseModel):
    """Input for find_join_path tool."""

    from_table: str = Field(description="Starting table name")
    to_table: str = Field(description="Target table name")
    from_schema: str = Field(description="Schema of the starting table")
    to_schema: str = Field(description="Schema of the target table")
    max_depth: int = Field(
        default=4,
        ge=1,
        le=6,
        description="Maximum number of joins to traverse (1-6)",
    )


class JoinStep(BaseModel):
    """A single step in a join path between two tables."""

    from_schema: str = Field(description="Schema of the source table in this step")
    from_table: str = Field(description="Source table in this step")
    from_column: str = Field(description="Join column in the source table")
    to_schema: str = Field(description="Schema of the target table in this step")
    to_table: str = Field(description="Target table in this step")
    to_column: str = Field(description="Join column in the target table")
    constraint_name: str = Field(description="FK constraint used for this join")
    direction: Literal["outgoing", "incoming"] = Field(
        description="Direction of the FK: 'outgoing' if following FK from source, "
        "'incoming' if traversing FK in reverse"
    )


class JoinPath(BaseModel):
    """A complete join path between two tables with SQL example."""

    steps: list[JoinStep] = Field(description="Ordered list of join steps")
    length: int = Field(description="Number of joins in this path")
    sql_example: str = Field(description="Generated SQL JOIN clause example for this path")


class FindJoinPathOutput(BaseModel):
    """Output for find_join_path tool."""

    from_table: str = Field(description="Starting table name")
    to_table: str = Field(description="Target table name")
    paths: list[JoinPath] = Field(
        default_factory=list,
        description="Join paths sorted by length (shortest first)",
    )
    path_count: int = Field(description="Number of paths found")
