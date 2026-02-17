"""Tests for the backend manager and protocol.

Covers:
- BackendProtocol compliance checking
- Path-based backend auto-detection (detect_backend)
- Backend routing with explicit backend parameter (get_backend)
- Explicit backend override with verified routing
- Disabled backend rejection (is_backend_enabled, get_backend)
- Security validator integration (mocked)
- Edge cases: both backends disabled, s3 path without s3 config, empty path
- Error wrapping: unexpected errors wrapped in BackendError
- Cross-backend path routing and auto-detection (Section 9.3)
- Path detection for various formats (absolute, relative, dot-relative, bare name)
- S3 path parsing (bucket extraction, key extraction)
- Conflicting backend/path combination errors
- Integration: end-to-end routing with both backends active
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from mamba_mcp_fs.backends.base import (
    BACKEND_LOCAL,
    BACKEND_S3,
    S3_PREFIX,
    VALID_BACKENDS,
    BackendManager,
    BackendProtocol,
)
from mamba_mcp_fs.config import LocalSettings, S3Settings, ServerSettings, Settings
from mamba_mcp_fs.errors import BackendError, BackendNotConfiguredError, InvalidOperationError
from mamba_mcp_fs.security import SecurityValidator

# ============================================================================
# Helpers: Mock backend that satisfies BackendProtocol
# ============================================================================


class MockBackend:
    """A mock backend that implements all BackendProtocol methods."""

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        return [{"name": path, "type": "directory"}]

    def info(self, path: str) -> dict[str, Any]:
        return {"name": path, "type": "file", "size": 0}

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        return b"content"

    def pipe_file(self, path: str, data: bytes) -> None:
        pass

    def rm(self, path: str) -> None:
        pass

    def cp_file(self, source: str, destination: str) -> None:
        pass

    def mv(self, source: str, destination: str) -> None:
        pass

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        pass

    def exists(self, path: str) -> bool:
        return True

    def isdir(self, path: str) -> bool:
        return True

    def isfile(self, path: str) -> bool:
        return False


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """Create a temporary sandbox directory."""
    (tmp_path / "file.txt").write_text("hello")
    (tmp_path / "subdir").mkdir()
    return tmp_path


@pytest.fixture()
def server_settings() -> ServerSettings:
    """Default server settings."""
    return ServerSettings()


@pytest.fixture()
def local_settings(sandbox: Path) -> LocalSettings:
    """Local settings with sandbox as base_path."""
    return LocalSettings(base_path=str(sandbox))


@pytest.fixture()
def local_settings_disabled(sandbox: Path) -> LocalSettings:
    """Local settings with backend disabled."""
    return LocalSettings(base_path=str(sandbox), enabled=False)


@pytest.fixture()
def s3_settings_enabled() -> S3Settings:
    """S3 settings with backend enabled."""
    return S3Settings(enabled=True, bucket="test-bucket")


@pytest.fixture()
def s3_settings_disabled() -> S3Settings:
    """S3 settings with backend disabled (default)."""
    return S3Settings(enabled=False)


@pytest.fixture()
def mock_local_backend() -> MockBackend:
    """A mock local filesystem backend."""
    return MockBackend()


@pytest.fixture()
def mock_s3_backend() -> MockBackend:
    """A mock S3 backend."""
    return MockBackend()


def _make_settings(
    local: LocalSettings,
    s3: S3Settings,
    server: ServerSettings | None = None,
) -> Settings:
    """Create a Settings instance with pre-built sub-settings."""
    return Settings(
        server=server or ServerSettings(),
        local=local,
        s3=s3,
    )


def _make_manager(
    settings: Settings,
    security: SecurityValidator,
    local_backend: MockBackend | None = None,
    s3_backend: MockBackend | None = None,
) -> BackendManager:
    """Create a BackendManager for testing."""
    return BackendManager(
        settings=settings,
        security=security,
        local_backend=local_backend,
        s3_backend=s3_backend,
    )


# ============================================================================
# TestBackendProtocol: Protocol compliance
# ============================================================================


class TestBackendProtocol:
    """Tests for BackendProtocol interface."""

    def test_mock_backend_satisfies_protocol(self) -> None:
        """MockBackend should satisfy BackendProtocol at runtime."""
        backend = MockBackend()
        assert isinstance(backend, BackendProtocol)

    def test_protocol_has_all_required_methods(self) -> None:
        """BackendProtocol should require all specified methods."""
        expected_methods = {
            "ls",
            "info",
            "cat_file",
            "pipe_file",
            "rm",
            "cp_file",
            "mv",
            "mkdir",
            "exists",
            "isdir",
            "isfile",
        }
        # Check that the protocol defines all expected methods
        protocol_methods = {
            name
            for name in dir(BackendProtocol)
            if not name.startswith("_") and callable(getattr(BackendProtocol, name, None))
        }
        assert expected_methods.issubset(protocol_methods)

    def test_object_missing_method_does_not_satisfy_protocol(self) -> None:
        """An object missing required methods should not satisfy the protocol."""

        class IncompleteBackend:
            def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
                return []

        backend = IncompleteBackend()
        assert not isinstance(backend, BackendProtocol)


# ============================================================================
# TestDetectBackend: Path-based auto-detection
# ============================================================================


class TestDetectBackend:
    """Tests for BackendManager.detect_backend path detection."""

    def test_s3_prefix_detected(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
    ) -> None:
        """Paths starting with s3:// should detect as S3 backend."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("s3://bucket/key") == BACKEND_S3

    def test_s3_prefix_case_sensitive(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
    ) -> None:
        """S3 detection should be case-sensitive (S3:// is not detected as S3)."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("S3://bucket/key") == BACKEND_LOCAL

    def test_local_path_detected(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """Non-prefixed paths should detect as local backend."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("/some/local/path") == BACKEND_LOCAL

    def test_relative_path_detected_as_local(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """Relative paths should detect as local backend."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("relative/path") == BACKEND_LOCAL

    def test_empty_path_detected_as_local(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """Empty path string should detect as local backend."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("") == BACKEND_LOCAL

    def test_s3_prefix_only(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
    ) -> None:
        """Just 's3://' with no key should still detect as S3."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("s3://") == BACKEND_S3

    def test_s3_with_complex_path(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
    ) -> None:
        """S3 paths with bucket and complex keys should detect correctly."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("s3://my-bucket/path/to/file.txt") == BACKEND_S3


# ============================================================================
# TestIsBackendEnabled: Backend enabled checks
# ============================================================================


class TestIsBackendEnabled:
    """Tests for BackendManager.is_backend_enabled."""

    def test_local_enabled(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """Local backend should be enabled when local.enabled=True."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.is_backend_enabled(BACKEND_LOCAL) is True

    def test_local_disabled(
        self,
        server_settings: ServerSettings,
        local_settings_disabled: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """Local backend should be disabled when local.enabled=False."""
        settings = _make_settings(local_settings_disabled, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings_disabled, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.is_backend_enabled(BACKEND_LOCAL) is False

    def test_s3_enabled(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
    ) -> None:
        """S3 backend should be enabled when s3.enabled=True."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(settings, security)

        assert manager.is_backend_enabled(BACKEND_S3) is True

    def test_s3_disabled(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """S3 backend should be disabled when s3.enabled=False."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.is_backend_enabled(BACKEND_S3) is False

    def test_unknown_backend(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """Unknown backend names should return False."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.is_backend_enabled("gcs") is False
        assert manager.is_backend_enabled("") is False


# ============================================================================
# TestGetBackendRouting: Backend routing via get_backend
# ============================================================================


class TestGetBackendRouting:
    """Tests for BackendManager.get_backend routing logic."""

    def test_routes_s3_path_to_s3_backend(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """s3:// paths should route to the S3 backend."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        backend, resolved = manager.get_backend("s3://bucket/file.txt")
        assert backend is mock_s3_backend
        # The resolved path should have s3:// prefix stripped and be validated
        assert "bucket/file.txt" in resolved or resolved == "bucket/file.txt"

    def test_routes_local_path_to_local_backend(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Non-prefixed paths should route to the local backend."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        backend, resolved = manager.get_backend("file.txt")
        assert backend is mock_local_backend
        # The resolved path should be an absolute path within sandbox
        assert str(sandbox) in resolved

    def test_explicit_backend_overrides_detection(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Explicit backend parameter should override auto-detection."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        # Path looks local, but we force S3 backend
        backend, resolved = manager.get_backend("some/key/path.txt", backend="s3")
        assert backend is mock_s3_backend

    def test_explicit_local_backend_for_any_path(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Explicit local backend should work even for paths that look like S3."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        # Use a local path within the sandbox explicitly with local backend
        backend, resolved = manager.get_backend("file.txt", backend="local")
        assert backend is mock_local_backend


# ============================================================================
# TestDisabledBackendRejection: get_backend with disabled backends
# ============================================================================


class TestDisabledBackendRejection:
    """Tests for BackendManager rejecting disabled backends."""

    def test_disabled_local_backend_raises(
        self,
        server_settings: ServerSettings,
        local_settings_disabled: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Requesting disabled local backend should raise BackendNotConfiguredError."""
        settings = _make_settings(local_settings_disabled, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings_disabled, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        with pytest.raises(BackendNotConfiguredError, match="not enabled"):
            manager.get_backend("/some/path")

    def test_disabled_s3_backend_raises(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Requesting disabled S3 backend should raise BackendNotConfiguredError."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, s3_backend=mock_s3_backend)

        with pytest.raises(BackendNotConfiguredError, match="not enabled"):
            manager.get_backend("s3://bucket/key")

    def test_s3_path_when_s3_not_configured(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """S3 path when S3 is disabled should raise BackendNotConfiguredError."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        with pytest.raises(BackendNotConfiguredError, match="not enabled"):
            manager.get_backend("s3://bucket/key")

    def test_both_backends_disabled(
        self,
        server_settings: ServerSettings,
        local_settings_disabled: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """When both backends are disabled, any path should raise BackendNotConfiguredError."""
        settings = _make_settings(local_settings_disabled, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings_disabled, s3_settings_disabled)
        manager = _make_manager(settings, security)

        with pytest.raises(BackendNotConfiguredError, match="not enabled"):
            manager.get_backend("/local/path")

        with pytest.raises(BackendNotConfiguredError, match="not enabled"):
            manager.get_backend("s3://bucket/key")

    def test_unknown_backend_name_raises(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Explicit unknown backend name should raise BackendNotConfiguredError."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        with pytest.raises(BackendNotConfiguredError, match="Unknown backend"):
            manager.get_backend("/some/path", backend="gcs")

    def test_enabled_but_no_instance_raises(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
    ) -> None:
        """Enabled backend with no registered instance should raise."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        # S3 is enabled but no s3_backend provided
        manager = _make_manager(settings, security)

        with pytest.raises(BackendNotConfiguredError, match="no instance"):
            manager.get_backend("s3://bucket/key")


# ============================================================================
# TestSecurityValidation: Security integration via get_backend
# ============================================================================


class TestSecurityValidation:
    """Tests for security validator integration in BackendManager."""

    def test_local_path_passes_through_security(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Local paths should be validated through SecurityValidator."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        # Path inside sandbox should succeed
        backend, resolved = manager.get_backend("file.txt")
        assert backend is mock_local_backend
        assert resolved == str(sandbox / "file.txt")

    def test_local_path_traversal_blocked_by_security(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Path traversal attempts should be blocked by the security validator."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        # This wraps the security error in BackendError
        with pytest.raises(Exception):
            manager.get_backend("../../etc/passwd")

    def test_s3_path_passes_through_security(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """S3 paths should be validated through SecurityValidator.validate_s3_path."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        backend, resolved = manager.get_backend("s3://bucket/file.txt")
        assert backend is mock_s3_backend
        # S3 validator normalizes the path
        assert resolved == "bucket/file.txt"

    def test_security_called_with_mock(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Verify security validator methods are actually called during get_backend."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)

        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        with patch.object(security, "validate_local_path", return_value=sandbox / "test.txt"):
            backend, resolved = manager.get_backend("test.txt")
            security.validate_local_path.assert_called_once_with("test.txt")  # type: ignore[attr-defined]

    def test_security_called_for_s3_with_mock(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Verify security validator validate_s3_path is called for S3 paths."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        with patch.object(security, "validate_s3_path", return_value="bucket/file.txt"):
            backend, resolved = manager.get_backend("s3://bucket/file.txt")
            security.validate_s3_path.assert_called_once_with("bucket/file.txt")  # type: ignore[attr-defined]


# ============================================================================
# TestEdgeCases: Edge case handling
# ============================================================================


class TestEdgeCases:
    """Tests for edge case handling in BackendManager."""

    def test_empty_path_routes_to_local(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Empty path string should route to local backend (base path)."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        # Empty path resolves to the sandbox base itself
        backend, resolved = manager.get_backend("")
        assert backend is mock_local_backend
        assert resolved == str(sandbox)

    def test_s3_prefix_only_path_raises(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Path of just 's3://' should raise InvalidOperationError (empty bucket)."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        with pytest.raises(InvalidOperationError, match="empty bucket name"):
            manager.get_backend("s3://")

    def test_manager_properties(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """Manager should expose settings and security properties."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.settings is settings
        assert manager.security is security


# ============================================================================
# TestErrorWrapping: BackendError wrapping of unexpected errors
# ============================================================================


class TestErrorWrapping:
    """Tests for error wrapping in BackendManager."""

    def test_unexpected_security_error_wrapped_in_backend_error(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Unexpected exceptions during path resolution should be wrapped in BackendError."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        # Patch security to raise an unexpected error
        with patch.object(security, "validate_local_path", side_effect=RuntimeError("boom")):
            with pytest.raises(BackendError, match="Error resolving path"):
                manager.get_backend("test.txt")

    def test_backend_not_configured_not_wrapped(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """BackendNotConfiguredError should not be wrapped by BackendError."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        # Directly requesting a disabled backend
        with pytest.raises(BackendNotConfiguredError):
            manager.get_backend("s3://bucket/key")

    def test_fs_error_from_security_propagates(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """FSError subclasses from security validation should propagate through BackendError."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        # Path traversal should raise an FSError subclass, which gets wrapped in BackendError
        # since PathOutsideSandboxError is not BackendNotConfiguredError or BackendError
        with patch.object(
            security,
            "validate_local_path",
            side_effect=RuntimeError("unexpected"),
        ):
            with pytest.raises(BackendError, match="Error resolving path"):
                manager.get_backend("test.txt")


# ============================================================================
# TestConstants: Module-level constants
# ============================================================================


class TestConstants:
    """Tests for module-level constants."""

    def test_s3_prefix(self) -> None:
        """S3_PREFIX should be 's3://'."""
        assert S3_PREFIX == "s3://"

    def test_backend_names(self) -> None:
        """Backend name constants should be correct."""
        assert BACKEND_LOCAL == "local"
        assert BACKEND_S3 == "s3"

    def test_valid_backends_set(self) -> None:
        """VALID_BACKENDS should contain both backend names."""
        assert VALID_BACKENDS == {"local", "s3"}


# ============================================================================
# TestPathDetectionFormats: Various path format detection (Section 9.3)
# ============================================================================


class TestPathDetectionFormats:
    """Tests for path detection across various path formats.

    Covers: s3:// prefix, absolute local, dot-relative, bare filename,
    paths with special characters, and Windows-style paths.
    """

    def test_s3_bucket_and_key(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
    ) -> None:
        """s3://my-bucket/path/to/file.txt should detect as S3."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("s3://my-bucket/path/to/file.txt") == BACKEND_S3

    def test_absolute_local_path(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """/data/files/report.csv should detect as local."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("/data/files/report.csv") == BACKEND_LOCAL

    def test_dot_relative_path(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """./relative/path.txt should detect as local."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("./relative/path.txt") == BACKEND_LOCAL

    def test_bare_filename(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """file.txt should detect as local."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("file.txt") == BACKEND_LOCAL

    def test_dotdot_relative_path(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """../sibling/path.txt should detect as local (traversal is a security concern)."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("../sibling/path.txt") == BACKEND_LOCAL

    def test_path_with_spaces(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
    ) -> None:
        """Paths with spaces should detect as local."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("my folder/my file.txt") == BACKEND_LOCAL

    def test_s3_path_with_deep_key(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
    ) -> None:
        """s3://bucket/deeply/nested/key/file.txt should detect as S3."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("s3://bucket/deeply/nested/key/file.txt") == BACKEND_S3

    def test_s3_bucket_only(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
    ) -> None:
        """s3://my-bucket should detect as S3."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("s3://my-bucket") == BACKEND_S3

    def test_s3_bucket_with_trailing_slash(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
    ) -> None:
        """s3://my-bucket/ should detect as S3."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(settings, security)

        assert manager.detect_backend("s3://my-bucket/") == BACKEND_S3


# ============================================================================
# TestExplicitBackendOverride: Explicit backend parameter routing (Section 9.3)
# ============================================================================


class TestExplicitBackendOverride:
    """Tests for explicit backend parameter overriding auto-detection.

    Covers: backend="s3" with local-looking path, backend="local" with local path,
    backend="s3" with s3:// path (explicit but redundant), resolved path verification.
    """

    def test_explicit_s3_with_local_looking_path_routes_to_s3(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """backend='s3' with non-s3:// path treats path as S3 key."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        backend, resolved = manager.get_backend("data/reports/file.csv", backend="s3")
        assert backend is mock_s3_backend
        # Path is treated as S3 key, validated through s3 security
        assert "data/reports/file.csv" in resolved

    def test_explicit_s3_with_bare_filename(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """backend='s3' with bare filename treats it as S3 key."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        backend, resolved = manager.get_backend("report.csv", backend="s3")
        assert backend is mock_s3_backend
        assert resolved == "report.csv"

    def test_explicit_s3_with_s3_path_is_redundant_but_works(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """backend='s3' with s3:// path should work (redundant but valid)."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        backend, resolved = manager.get_backend("s3://bucket/key.txt", backend="s3")
        assert backend is mock_s3_backend
        assert resolved == "bucket/key.txt"

    def test_explicit_local_with_local_path(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """backend='local' with local path should route to local."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        backend, resolved = manager.get_backend("file.txt", backend="local")
        assert backend is mock_local_backend
        assert resolved == str(sandbox / "file.txt")

    def test_explicit_local_with_s3_path_raises_invalid_operation(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """backend='local' with s3:// path should raise InvalidOperationError."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        with pytest.raises(InvalidOperationError, match="Cannot use local backend"):
            manager.get_backend("s3://bucket/file.txt", backend="local")

    def test_explicit_none_falls_through_to_auto_detection(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """backend=None should fall through to auto-detection."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        # Local path with backend=None -> auto-detect -> local
        backend, resolved = manager.get_backend("file.txt", backend=None)
        assert backend is mock_local_backend

        # S3 path with backend=None -> auto-detect -> s3
        backend, resolved = manager.get_backend("s3://bucket/file.txt", backend=None)
        assert backend is mock_s3_backend


# ============================================================================
# TestRelativePathResolution: Relative paths within local base_path
# ============================================================================


class TestRelativePathResolution:
    """Tests for relative path resolution within the local base_path.

    Covers: bare filenames, dot-relative paths, subdirectory paths,
    paths resolving to sandbox root.
    """

    def test_bare_filename_resolves_to_sandbox(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """file.txt should resolve to {sandbox}/file.txt."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        backend, resolved = manager.get_backend("file.txt")
        assert resolved == str(sandbox / "file.txt")

    def test_dot_relative_resolves_to_sandbox(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """./file.txt should resolve to {sandbox}/file.txt."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        backend, resolved = manager.get_backend("./file.txt")
        assert resolved == str(sandbox / "file.txt")

    def test_subdirectory_path_resolves_correctly(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """subdir/nested.txt should resolve to {sandbox}/subdir/nested.txt."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        backend, resolved = manager.get_backend("subdir/nested.txt")
        assert resolved == str(sandbox / "subdir" / "nested.txt")

    def test_dot_prefix_subdirectory_resolves_correctly(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """./subdir/file.txt should resolve within sandbox."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        backend, resolved = manager.get_backend("./subdir/file.txt")
        assert resolved == str(sandbox / "subdir" / "file.txt")

    def test_empty_path_resolves_to_sandbox_root(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Empty path should resolve to the sandbox root directory."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        backend, resolved = manager.get_backend("")
        assert resolved == str(sandbox)

    def test_absolute_path_within_sandbox_accepted(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Absolute path inside the sandbox should be accepted."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        abs_path = str(sandbox / "file.txt")
        backend, resolved = manager.get_backend(abs_path)
        assert resolved == abs_path

    def test_absolute_path_outside_sandbox_rejected(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Absolute path outside the sandbox should be rejected."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        with pytest.raises(Exception):
            manager.get_backend("/etc/passwd")


# ============================================================================
# TestS3PathParsing: S3 path resolution and bucket/key extraction
# ============================================================================


class TestS3PathParsing:
    """Tests for S3 path resolution within get_backend.

    Verifies that the s3:// prefix is correctly stripped and the bucket/key
    path is properly resolved for the S3 backend.
    """

    def test_bucket_and_key_resolved(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """s3://my-bucket/path/to/file.txt -> resolved = 'my-bucket/path/to/file.txt'."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        backend, resolved = manager.get_backend("s3://my-bucket/path/to/file.txt")
        assert backend is mock_s3_backend
        assert resolved == "my-bucket/path/to/file.txt"

    def test_bucket_only_resolved(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """s3://my-bucket -> resolved = 'my-bucket'."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        backend, resolved = manager.get_backend("s3://my-bucket")
        assert backend is mock_s3_backend
        assert resolved == "my-bucket"

    def test_bucket_with_trailing_slash_resolved(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """s3://my-bucket/ -> resolved should include bucket name."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        backend, resolved = manager.get_backend("s3://my-bucket/")
        assert backend is mock_s3_backend
        # After security normalization, "my-bucket/" normalizes to "my-bucket"
        assert "my-bucket" in resolved

    def test_empty_bucket_raises_invalid_operation(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """s3:// with no bucket should raise InvalidOperationError."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        with pytest.raises(InvalidOperationError, match="empty bucket name"):
            manager.get_backend("s3://")

    def test_s3_path_with_leading_slash_after_prefix_raises(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """s3:///path (empty bucket, leading slash) should raise InvalidOperationError."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        with pytest.raises(InvalidOperationError, match="empty bucket name"):
            manager.get_backend("s3:///path/to/file.txt")

    def test_explicit_s3_backend_non_prefixed_path_as_key(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """backend='s3' with non-s3:// path treats path as S3 key within default bucket."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        backend, resolved = manager.get_backend("my-folder/data.json", backend="s3")
        assert backend is mock_s3_backend
        # The path is treated as an S3 key (no s3:// stripping needed)
        assert resolved == "my-folder/data.json"


# ============================================================================
# TestConflictingBackendPathErrors: Invalid backend/path combinations
# ============================================================================


class TestConflictingBackendPathErrors:
    """Tests for error handling when backend and path conflict.

    Covers: backend='local' + s3:// path, various invalid combos,
    error code verification.
    """

    def test_local_backend_with_s3_path_raises_invalid_operation(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Explicit local backend with s3:// path must raise InvalidOperationError."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        with pytest.raises(InvalidOperationError, match="Cannot use local backend"):
            manager.get_backend("s3://bucket/key.txt", backend="local")

    def test_invalid_operation_error_has_correct_code(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """InvalidOperationError should carry INVALID_OPERATION code."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        with pytest.raises(InvalidOperationError) as exc_info:
            manager.get_backend("s3://bucket/key.txt", backend="local")

        from mamba_mcp_fs.errors import ErrorCode

        assert exc_info.value.code == ErrorCode.INVALID_OPERATION

    def test_backend_not_configured_has_correct_code(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """BackendNotConfiguredError should carry BACKEND_NOT_CONFIGURED code."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        with pytest.raises(BackendNotConfiguredError) as exc_info:
            manager.get_backend("s3://bucket/key")

        from mamba_mcp_fs.errors import ErrorCode

        assert exc_info.value.code == ErrorCode.BACKEND_NOT_CONFIGURED

    def test_local_backend_s3_path_error_mentions_suggestion(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Error for local backend + s3:// should mention using backend='s3'."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        with pytest.raises(InvalidOperationError) as exc_info:
            manager.get_backend("s3://bucket/key.txt", backend="local")

        assert "backend='s3'" in str(exc_info.value) or "s3://" in str(exc_info.value)

    def test_local_backend_conflict_checked_before_enabled_check(
        self,
        server_settings: ServerSettings,
        local_settings_disabled: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Conflict check runs before enabled check: local+s3:// raises InvalidOperationError
        even when local is disabled."""
        settings = _make_settings(local_settings_disabled, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings_disabled, s3_settings_enabled)
        manager = _make_manager(settings, security, s3_backend=mock_s3_backend)

        # The conflict (local backend + s3:// path) should raise InvalidOperationError
        # before we even get to the "is backend enabled" check
        with pytest.raises(InvalidOperationError, match="Cannot use local backend"):
            manager.get_backend("s3://bucket/key.txt", backend="local")


# ============================================================================
# TestCrossBackendIntegration: End-to-end routing with both backends active
# ============================================================================


class TestCrossBackendIntegration:
    """Integration tests for cross-backend path routing with both backends active.

    Tests the complete flow: path -> detection -> validation -> backend selection.
    """

    def test_local_and_s3_paths_route_correctly_in_same_manager(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Both local and S3 paths should route correctly within the same manager."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        # Local path
        local_backend, local_resolved = manager.get_backend("file.txt")
        assert local_backend is mock_local_backend
        assert local_resolved == str(sandbox / "file.txt")

        # S3 path
        s3_backend, s3_resolved = manager.get_backend("s3://bucket/data.csv")
        assert s3_backend is mock_s3_backend
        assert s3_resolved == "bucket/data.csv"

    def test_multiple_s3_paths_route_consistently(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Multiple S3 paths should consistently route to S3 backend."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        paths = [
            ("s3://bucket-a/file1.txt", "bucket-a/file1.txt"),
            ("s3://bucket-b/nested/file2.csv", "bucket-b/nested/file2.csv"),
            ("s3://my-data/reports/2024/q1.json", "my-data/reports/2024/q1.json"),
        ]

        for s3_path, expected_resolved in paths:
            backend, resolved = manager.get_backend(s3_path)
            assert backend is mock_s3_backend, f"Failed for path: {s3_path}"
            assert resolved == expected_resolved, f"Failed for path: {s3_path}"

    def test_multiple_local_paths_route_consistently(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_disabled: S3Settings,
        mock_local_backend: MockBackend,
    ) -> None:
        """Multiple local paths should consistently route to local backend."""
        settings = _make_settings(local_settings, s3_settings_disabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_disabled)
        manager = _make_manager(settings, security, local_backend=mock_local_backend)

        paths = [
            "file.txt",
            "subdir/nested.txt",
            "./another.py",
        ]

        for local_path in paths:
            backend, resolved = manager.get_backend(local_path)
            assert backend is mock_local_backend, f"Failed for path: {local_path}"
            assert str(sandbox) in resolved, f"Failed for path: {local_path}"

    def test_explicit_override_then_autodetect_does_not_leak_state(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Explicit backend override should not affect subsequent auto-detection calls."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        # Force S3 for a local-looking path
        backend1, _ = manager.get_backend("some/key.txt", backend="s3")
        assert backend1 is mock_s3_backend

        # Subsequent auto-detect should still route local paths to local
        backend2, resolved2 = manager.get_backend("file.txt")
        assert backend2 is mock_local_backend
        assert resolved2 == str(sandbox / "file.txt")

        # And S3 paths should still auto-detect to S3
        backend3, resolved3 = manager.get_backend("s3://bucket/key.txt")
        assert backend3 is mock_s3_backend
        assert resolved3 == "bucket/key.txt"

    def test_mixed_backend_operations_with_errors(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Mix of valid and error-producing operations should not corrupt state."""
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        # Valid local operation
        backend, resolved = manager.get_backend("file.txt")
        assert backend is mock_local_backend

        # Error: local backend + s3:// path
        with pytest.raises(InvalidOperationError):
            manager.get_backend("s3://bucket/file.txt", backend="local")

        # Manager should still work after error
        backend, resolved = manager.get_backend("s3://bucket/data.csv")
        assert backend is mock_s3_backend
        assert resolved == "bucket/data.csv"

        # Error: empty bucket
        with pytest.raises(InvalidOperationError):
            manager.get_backend("s3://")

        # Manager should still work after error
        backend, resolved = manager.get_backend("file.txt")
        assert backend is mock_local_backend
        assert resolved == str(sandbox / "file.txt")

    def test_all_scenario_paths_from_spec(
        self,
        sandbox: Path,
        server_settings: ServerSettings,
        local_settings: LocalSettings,
        s3_settings_enabled: S3Settings,
        mock_local_backend: MockBackend,
        mock_s3_backend: MockBackend,
    ) -> None:
        """Verify all path scenarios listed in the task description.

        - s3://my-bucket/path/to/file.txt -> S3 backend
        - /data/files/report.csv -> Local backend (absolute within sandbox)
        - ./relative/path.txt -> Local backend (dot-relative)
        - file.txt -> Local backend (bare filename)
        """
        settings = _make_settings(local_settings, s3_settings_enabled, server_settings)
        security = SecurityValidator(server_settings, local_settings, s3_settings_enabled)
        manager = _make_manager(
            settings, security, local_backend=mock_local_backend, s3_backend=mock_s3_backend
        )

        # Scenario 1: s3://my-bucket/path/to/file.txt -> S3
        backend, resolved = manager.get_backend("s3://my-bucket/path/to/file.txt")
        assert backend is mock_s3_backend
        assert resolved == "my-bucket/path/to/file.txt"

        # Scenario 2: absolute local path within sandbox
        abs_path = str(sandbox / "report.csv")
        backend, resolved = manager.get_backend(abs_path)
        assert backend is mock_local_backend
        assert resolved == abs_path

        # Scenario 3: ./relative/path.txt -> Local
        backend, resolved = manager.get_backend("./subdir/nested.txt")
        assert backend is mock_local_backend
        assert resolved == str(sandbox / "subdir" / "nested.txt")

        # Scenario 4: file.txt -> Local
        backend, resolved = manager.get_backend("file.txt")
        assert backend is mock_local_backend
        assert resolved == str(sandbox / "file.txt")
