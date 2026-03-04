"""
Tests for Phase 3B.6: SSHOrchestrator

Coverage:
- Remote command execution
- Signature verification
- Sandboxing policies
- Connection management
- Audit logging
"""

import pytest
import time
import hmac
import hashlib

from ace.distributed.ssh_orchestrator import (
    SSHOrchestrator,
    SSHConnectionPool,
    ExecutionMode,
    SandboxPolicy,
)
from ace.distributed.data_structures import RemoteCommand


class TestSSHOrchestrator:
    """Test SSHOrchestrator functionality."""

    def test_initialization(self):
        """SSHOrchestrator initializes correctly."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(key)

        assert orchestrator._cluster_key == key
        assert orchestrator._sandbox_policy == SandboxPolicy.STANDARD

    def test_command_signature_valid(self):
        """Valid signatures are accepted."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(key)

        # Build command
        cmd_id = "cmd_1"
        executable = "echo"
        args = ["hello"]

        # Compute signature
        payload = f"{cmd_id}:{executable}:{':'.join(args)}"
        signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()

        cmd = RemoteCommand(
            command_id=cmd_id,
            node_id="node_1",
            executable=executable,
            args=args,
            env={},
            timeout_ms=5000,
            signature=signature,
        )

        assert orchestrator.verify_signature(cmd) is True

    def test_command_signature_invalid(self):
        """Invalid signatures are rejected."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(key)

        cmd = RemoteCommand(
            command_id="cmd_1",
            node_id="node_1",
            executable="echo",
            args=["hello"],
            env={},
            timeout_ms=5000,
            signature="invalid_signature_12345",
        )

        assert orchestrator.verify_signature(cmd) is False

    def test_execute_echo_command(self):
        """Execute simple echo command."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(
            key, sandbox_policy=SandboxPolicy.PERMISSIVE
        )

        # Build command - use python instead of echo for cross-platform compatibility
        cmd_id = "cmd_2"
        executable = "python"
        args = ["-c", "print('test')"]

        payload = f"{cmd_id}:{executable}:{':'.join(args)}"
        signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()

        cmd = RemoteCommand(
            command_id=cmd_id,
            node_id="node_1",
            executable=executable,
            args=args,
            env={},
            timeout_ms=5000,
            signature=signature,
        )

        result = orchestrator.execute_remote(cmd)

        assert result.success is True
        assert result.exit_code == 0
        assert "test" in result.stdout

    def test_execute_command_with_failure(self):
        """Execute command that fails."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(
            key, sandbox_policy=SandboxPolicy.PERMISSIVE
        )

        # Build command that fails - use python with exit code
        cmd_id = "cmd_3"
        executable = "python"
        args = ["-c", "import sys; sys.exit(1)"]

        payload = f"{cmd_id}:{executable}:{':'.join(args)}"
        signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()

        cmd = RemoteCommand(
            command_id=cmd_id,
            node_id="node_1",
            executable=executable,
            args=args,
            env={},
            timeout_ms=5000,
            signature=signature,
        )

        result = orchestrator.execute_remote(cmd)

        assert result.success is False
        assert result.exit_code != 0

    def test_command_signature_rejection_fails_execution(self):
        """Execution fails if signature doesn't verify."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(key)

        cmd = RemoteCommand(
            command_id="cmd_4",
            node_id="node_1",
            executable="echo",
            args=["hello"],
            env={},
            timeout_ms=5000,
            signature="wrong_signature",
        )

        result = orchestrator.execute_remote(cmd)

        assert result.success is False
        assert "Signature" in result.stderr or "verification" in result.stderr.lower()

    def test_establish_connection(self):
        """Establish SSH connection."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(key)

        success = orchestrator.establish_connection("node_1", "localhost", 22)

        assert success is True

    def test_close_connection(self):
        """Close SSH connection."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(key)

        orchestrator.establish_connection("node_1", "localhost", 22)
        orchestrator.close_connection("node_1")

        # Connection should be marked closed
        assert orchestrator._connections["node_1"]["status"] == "CLOSED"

    def test_get_command_result(self):
        """Retrieve cached command result."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(
            key, sandbox_policy=SandboxPolicy.PERMISSIVE
        )

        # Execute command
        cmd_id = "cmd_5"
        executable = "python"
        args = ["-c", "print('test')"]

        payload = f"{cmd_id}:{executable}:{':'.join(args)}"
        signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()

        cmd = RemoteCommand(
            command_id=cmd_id,
            node_id="node_1",
            executable=executable,
            args=args,
            env={},
            timeout_ms=5000,
            signature=signature,
        )

        result1 = orchestrator.execute_remote(cmd)

        # Retrieve cached result
        result2 = orchestrator.get_command_result(cmd_id)

        assert result2 is not None
        assert result2.command_id == cmd_id
        assert result2.success == result1.success

    def test_audit_trail(self):
        """Audit trail records executed commands."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(
            key, sandbox_policy=SandboxPolicy.PERMISSIVE
        )

        # Execute a command
        cmd_id = "cmd_6"
        executable = "python"
        args = ["-c", "print('audit_test')"]

        payload = f"{cmd_id}:{executable}:{':'.join(args)}"
        signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()

        cmd = RemoteCommand(
            command_id=cmd_id,
            node_id="node_1",
            executable=executable,
            args=args,
            env={},
            timeout_ms=5000,
            signature=signature,
        )

        orchestrator.execute_remote(cmd)

        # Check audit trail
        audit = orchestrator.get_execution_audit()

        assert len(audit) == 1
        assert audit[0]["command_id"] == cmd_id
        assert audit[0]["node_id"] == "node_1"
        assert audit[0]["executable"] == executable

    def test_orchestrator_stats(self):
        """Get orchestrator statistics."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(
            key, sandbox_policy=SandboxPolicy.PERMISSIVE
        )

        # Execute multiple commands
        for i in range(3):
            cmd_id = f"cmd_{i}"
            executable = "python"
            args = ["-c", f"print('test_{i}')"]

            payload = f"{cmd_id}:{executable}:{':'.join(args)}"
            signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()

            cmd = RemoteCommand(
                command_id=cmd_id,
                node_id="node_1",
                executable=executable,
                args=args,
                env={},
                timeout_ms=5000,
                signature=signature,
            )

            orchestrator.execute_remote(cmd)

        stats = orchestrator.get_orchestrator_stats()

        assert stats["total_commands"] == 3
        assert stats["successful_commands"] >= 1


class TestSSHConnectionPool:
    """Test SSHConnectionPool functionality."""

    def test_pool_initialization(self):
        """Connection pool initializes correctly."""
        pool = SSHConnectionPool(max_connections=5)

        assert pool._max_connections == 5

    def test_acquire_new_connection(self):
        """Acquire new connection from pool."""
        pool = SSHConnectionPool(max_connections=5)

        conn = pool.acquire("node_1")

        assert conn is not None
        assert "node_1" in conn

    def test_release_connection(self):
        """Release connection back to pool."""
        pool = SSHConnectionPool(max_connections=5)

        conn1 = pool.acquire("node_1")
        pool.release("node_1", conn1)

        # Should reuse same connection
        conn2 = pool.acquire("node_1")
        assert conn2 == conn1

    def test_pool_respects_max_connections(self):
        """Pool doesn't exceed max connections."""
        pool = SSHConnectionPool(max_connections=2)

        conns = []
        for _ in range(2):
            conn = pool.acquire("node_1")
            assert conn is not None
            conns.append(conn)

        # Third acquire should fail
        conn3 = pool.acquire("node_1")
        assert conn3 is None

        # After release, should succeed
        pool.release("node_1", conns[0])
        conn4 = pool.acquire("node_1")
        assert conn4 == conns[0]

    def test_pool_per_node_isolation(self):
        """Connections are isolated per node."""
        pool = SSHConnectionPool(max_connections=2)

        conn1_node1 = pool.acquire("node_1")
        conn1_node2 = pool.acquire("node_2")

        assert conn1_node1 != conn1_node2

        conn2_node1 = pool.acquire("node_1")
        assert conn2_node1 != conn1_node1

    def test_pool_statistics(self):
        """Get pool statistics."""
        pool = SSHConnectionPool(max_connections=5)

        # Acquire some connections
        conns = []
        for i in range(3):
            conn = pool.acquire("node_1")
            conns.append(conn)

        # Release one
        pool.release("node_1", conns[0])

        stats = pool.get_pool_stats()

        assert stats["total_connections"] == 3
        assert stats["available_connections"] == 1
        assert stats["in_use_connections"] == 2
        assert stats["max_connections"] == 5


class TestSandboxPolicies:
    """Test sandbox execution policies."""

    def test_strict_sandbox_policy(self):
        """STRICT policy uses firejail."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(
            key, sandbox_policy=SandboxPolicy.STRICT
        )

        cmd = RemoteCommand(
            command_id="cmd_sandbox",
            node_id="node_1",
            executable="echo",
            args=["test"],
            env={},
            timeout_ms=5000,
            signature="fake",
        )

        sandbox_cmd = orchestrator._build_sandbox_command(cmd)

        # Should use firejail
        assert "firejail" in sandbox_cmd

    def test_standard_sandbox_policy(self):
        """STANDARD policy uses firejail with network."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(
            key, sandbox_policy=SandboxPolicy.STANDARD
        )

        cmd = RemoteCommand(
            command_id="cmd_sandbox",
            node_id="node_1",
            executable="echo",
            args=["test"],
            env={},
            timeout_ms=5000,
            signature="fake",
        )

        sandbox_cmd = orchestrator._build_sandbox_command(cmd)

        assert "firejail" in sandbox_cmd
        assert "--net=localhost" in sandbox_cmd

    def test_permissive_sandbox_policy(self):
        """PERMISSIVE policy has minimal restrictions."""
        key = b"test_cluster_key"
        orchestrator = SSHOrchestrator(
            key, sandbox_policy=SandboxPolicy.PERMISSIVE
        )

        cmd = RemoteCommand(
            command_id="cmd_sandbox",
            node_id="node_1",
            executable="echo",
            args=["test"],
            env={},
            timeout_ms=5000,
            signature="fake",
        )

        sandbox_cmd = orchestrator._build_sandbox_command(cmd)

        # Should be direct command
        assert sandbox_cmd[0] == "echo"
        assert "firejail" not in sandbox_cmd
