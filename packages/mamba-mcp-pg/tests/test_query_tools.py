"""Tests for query execution tools (Layer 3)."""

import pytest
from mamba_mcp_pg.database.queries import QueryService, QueryValidationError


class TestQuerySecurity:
    """Security tests for query validation (PRD Section 8.1)."""

    @pytest.mark.parametrize(
        "blocked_keyword",
        [
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "TRUNCATE",
            "ALTER",
            "CREATE",
            "GRANT",
            "REVOKE",
            "SET",
            "VACUUM",
            "ANALYZE",
            "COPY",
            "BEGIN",
            "COMMIT",
            "ROLLBACK",
        ],
    )
    def test_blocks_dangerous_keywords(self, blocked_keyword: str) -> None:
        """Test that all dangerous keywords are blocked."""
        service = QueryService(None, 30000)  # type: ignore

        with pytest.raises(QueryValidationError) as exc_info:
            service.validate_query(f"{blocked_keyword} something")

        assert exc_info.value.code == "WRITE_OPERATION_DENIED"

    def test_blocks_keywords_in_subquery(self) -> None:
        """Test that keywords in subqueries are blocked."""
        service = QueryService(None, 30000)  # type: ignore

        with pytest.raises(QueryValidationError):
            service.validate_query("SELECT * FROM (DELETE FROM users) AS x")

    def test_blocks_case_insensitive(self) -> None:
        """Test that keyword blocking is case-insensitive."""
        service = QueryService(None, 30000)  # type: ignore

        with pytest.raises(QueryValidationError):
            service.validate_query("insert into users values (1)")

        with pytest.raises(QueryValidationError):
            service.validate_query("INSERT into users values (1)")

        with pytest.raises(QueryValidationError):
            service.validate_query("InSeRt into users values (1)")

    def test_allows_select_statements(self) -> None:
        """Test that SELECT statements are allowed."""
        service = QueryService(None, 30000)  # type: ignore

        # Should not raise
        service.validate_query("SELECT * FROM users WHERE id = 1")
        service.validate_query("select id, name from users")
        service.validate_query("  SELECT * FROM users")  # Leading whitespace

    def test_allows_with_select_statements(self) -> None:
        """Test that WITH...SELECT statements are allowed."""
        service = QueryService(None, 30000)  # type: ignore

        # Should not raise
        service.validate_query("WITH cte AS (SELECT * FROM users) SELECT * FROM cte")
        service.validate_query(
            "with active_users as (select * from users where active) select * from active_users"
        )

    def test_rejects_non_select_start(self) -> None:
        """Test that queries not starting with SELECT/WITH are rejected."""
        service = QueryService(None, 30000)  # type: ignore

        with pytest.raises(QueryValidationError) as exc_info:
            service.validate_query("EXECUTE my_function()")

        assert exc_info.value.code == "INVALID_SQL"

    def test_blocks_delete_in_cte(self) -> None:
        """Test that DELETE in CTE is blocked."""
        service = QueryService(None, 30000)  # type: ignore

        with pytest.raises(QueryValidationError):
            service.validate_query(
                "WITH deleted AS (DELETE FROM users RETURNING *) SELECT * FROM deleted"
            )


class TestParameterHandling:
    """Tests for parameter conversion."""

    def test_converts_positional_params(self) -> None:
        """Test conversion of $1, $2 to :param_1, :param_2."""
        service = QueryService(None, 30000)  # type: ignore

        sql = "SELECT * FROM users WHERE id = $1 AND status = $2"
        params = [1, "active"]

        converted_sql, param_dict = service._convert_params(sql, params)

        assert ":param_1" in converted_sql
        assert ":param_2" in converted_sql
        assert "$1" not in converted_sql
        assert "$2" not in converted_sql
        assert param_dict["param_1"] == 1
        assert param_dict["param_2"] == "active"

    def test_handles_many_params(self) -> None:
        """Test handling of more than 9 parameters."""
        service = QueryService(None, 30000)  # type: ignore

        sql = "SELECT * FROM t WHERE a=$1 AND b=$2 AND c=$10 AND d=$11"
        params = list(range(1, 12))

        converted_sql, param_dict = service._convert_params(sql, params)

        # Make sure $10 and $11 are converted correctly (not $1 + "0")
        assert ":param_10" in converted_sql
        assert ":param_11" in converted_sql
        assert param_dict["param_10"] == 10
        assert param_dict["param_11"] == 11

    def test_handles_no_params(self) -> None:
        """Test handling of query with no parameters."""
        service = QueryService(None, 30000)  # type: ignore

        sql = "SELECT * FROM users"

        converted_sql, param_dict = service._convert_params(sql, None)

        assert converted_sql == sql
        assert param_dict == {}


class TestQueryHash:
    """Tests for query hashing."""

    def test_hash_is_consistent(self) -> None:
        """Test that the same query produces the same hash."""
        service = QueryService(None, 30000)  # type: ignore

        sql = "SELECT * FROM users"

        hash1 = service._hash_query(sql)
        hash2 = service._hash_query(sql)

        assert hash1 == hash2
        assert len(hash1) == 8  # 8 character hash

    def test_different_queries_different_hashes(self) -> None:
        """Test that different queries produce different hashes."""
        service = QueryService(None, 30000)  # type: ignore

        hash1 = service._hash_query("SELECT * FROM users")
        hash2 = service._hash_query("SELECT * FROM orders")

        assert hash1 != hash2
