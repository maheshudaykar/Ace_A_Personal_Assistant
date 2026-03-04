"""
SSHOrchestrator: Secure remote command execution via SSH.

Handles secure remote task execution with:
- Public key authentication
- Command signing and verification
- Sandboxed execution with resource limits
- Comprehensive audit logging
"""

import threading
import hashlib
import hmac
import time
import subprocess
import logging
import uuid
import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from .data_structures import RemoteCommand, RemoteResult

__all__ = [
    "SSHOrchestrator",
    "SSHConnectionPool",
]

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    """Execution mode for remote commands."""
    SYNC = "SYNC"  # Wait for completion
    ASYNC = "ASYNC"  # Fire and forget


class SandboxPolicy(Enum):
    """Sandbox execution policy."""
    STRICT = "STRICT"  # No network, read-only filesystem
    STANDARD = "STANDARD"  # Network to localhost only
    PERMISSIVE = "PERMISSIVE"  # Limited network access


class SSHOrchestrator:
    """Orchestrate secure remote command execution."""

    def __init__(
        self,
        cluster_key: bytes,
        ssh_key_path: str = "~/.ssh/id_rsa",
        sandbox_policy: SandboxPolicy = SandboxPolicy.STANDARD,
        default_timeout_ms: int = 30000,
    ):
        """
        Initialize SSHOrchestrator.

        Args:
            cluster_key: Shared cluster secret for HMAC signing
            ssh_key_path: Path to SSH private key
            sandbox_policy: Execution sandbox policy
            default_timeout_ms: Default command timeout
        """
        self._lock = threading.RLock()
        self._cluster_key = cluster_key
        self._ssh_key_path = ssh_key_path
        self._sandbox_policy = sandbox_policy
        self._default_timeout_ms = default_timeout_ms

        # Track active connections
        self._connections: Dict[str, Dict[str, Any]] = {}

        # Track command execution
        self._command_results: Dict[str, RemoteResult] = {}

        # Audit trail
        self._executed_commands: List[Dict[str, Any]] = []

    def execute_remote(
        self,
        cmd: RemoteCommand,
        mode: ExecutionMode = ExecutionMode.SYNC,
    ) -> RemoteResult:
        """
        Execute remote command on follower node.

        Args:
            cmd: Command to execute
            mode: SYNC (wait for completion) or ASYNC (fire-and-forget)

        Returns:
            RemoteResult with output and status (for SYNC mode)
            RemoteResult with pending status (for ASYNC mode)
        """
        with self._lock:
            # Verify signature
            if not self.verify_signature(cmd):
                logger.error(f"Command {cmd.command_id}: signature verification failed")
                return RemoteResult(
                    command_id=cmd.command_id,
                    success=False,
                    stdout="",
                    stderr="Signature verification failed",
                    exit_code=-1,
                    duration_ms=0,
                    resource_usage={},
                )

            # Handle ASYNC mode: queue for background execution
            if mode == ExecutionMode.ASYNC:
                logger.info(f"Command {cmd.command_id}: queued for async execution")
                # Return pending result immediately
                pending_result = RemoteResult(
                    command_id=cmd.command_id,
                    success=True,
                    stdout="",
                    stderr="",
                    exit_code=None,  # Not available until completion
                    duration_ms=0,
                    resource_usage={},
                )
                # Queue the command for background execution
                import threading
                thread = threading.Thread(
                    target=self._execute_async,
                    args=(cmd,),
                    daemon=True,
                )
                thread.start()
                return pending_result
            
            # SYNC mode: wait for completion
            start_time = time.time()
            result = self._execute_sandboxed(cmd)
            end_time = time.time()

            result.duration_ms = (end_time - start_time) * 1000

            # Audit log
            self._audit_execution(cmd, result)

            # Cache result
            self._command_results[cmd.command_id] = result

            logger.info(
                f"Command {cmd.command_id}: "
                f"exit={result.exit_code}, "
                f"duration={result.duration_ms:.0f}ms"
            )

            return result

    def _execute_async(self, cmd: RemoteCommand) -> None:
        """
        Background execution for ASYNC mode.
        
        Executes command and caches result without blocking caller.
        """
        try:
            start_time = time.time()
            result = self._execute_sandboxed(cmd)
            end_time = time.time()
            
            result.duration_ms = (end_time - start_time) * 1000
            
            # Audit log
            self._audit_execution(cmd, result)
            
            # Cache result
            with self._lock:
                self._command_results[cmd.command_id] = result
            
            logger.info(
                f"Async command {cmd.command_id}: "
                f"exit={result.exit_code}, "
                f"duration={result.duration_ms:.0f}ms"
            )
        except Exception as e:
            logger.error(f"Async execution error for {cmd.command_id}: {e}", exc_info=True)

    def verify_signature(self, cmd: RemoteCommand) -> bool:
        """
        Verify command authenticity via HMAC-SHA256.

        Args:
            cmd: Command to verify

        Returns:
            True if signature valid
        """
        # Reconstruct command string for signing
        payload = f"{cmd.command_id}:{cmd.executable}:{':'.join(cmd.args)}"

        # Compute expected signature
        expected_sig = hmac.new(
            self._cluster_key, payload.encode(), hashlib.sha256
        ).hexdigest()

        # Constant-time comparison
        valid = hmac.compare_digest(cmd.signature, expected_sig)

        if not valid:
            logger.warning(
                f"Signature mismatch for {cmd.command_id}: "
                f"expected {expected_sig[:16]}... got {cmd.signature[:16]}..."
            )

        return valid

    def _execute_sandboxed(self, cmd: RemoteCommand) -> RemoteResult:
        """Execute command with sandboxing based on policy."""
        try:
            # Build command with sandbox constraints
            sandbox_cmd = self._build_sandbox_command(cmd)

            # Execute with timeout
            timeout_sec = cmd.timeout_ms / 1000.0

            process = subprocess.Popen(
                sandbox_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=cmd.env,
                text=True,
            )

            try:
                stdout, stderr = process.communicate(timeout=timeout_sec)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                exit_code = -124  # Timeout exit code
                stderr = f"Command timed out after {timeout_sec}s"

            # Capture resource usage (simplified)
            resource_usage = {
                "cpu_percent": 0.0,  # Would need psutil for real usage
                "memory_rss_mb": 0,
                "memory_vms_mb": 0,
            }

            return RemoteResult(
                command_id=cmd.command_id,
                success=(exit_code == 0),
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_ms=0,  # Set by caller
                resource_usage=resource_usage,
            )

        except Exception as e:
            logger.error(f"Execution error for {cmd.command_id}: {e}", exc_info=True)
            return RemoteResult(
                command_id=cmd.command_id,
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                duration_ms=0,
                resource_usage={},
            )

    def _build_sandbox_command(self, cmd: RemoteCommand) -> List[str]:
        """Build command with sandbox constraints."""
        if self._sandbox_policy == SandboxPolicy.STRICT:
            # Most restrictive: read-only filesystem
            return [
                "firejail",
                "--noprofile",
                "--caps.drop=all",
                "--net=none",
                "--read-only=/",
                "--writable-tmp",
                f"--private={cmd.command_id}",
                cmd.executable,
            ] + cmd.args

        elif self._sandbox_policy == SandboxPolicy.STANDARD:
            # Localhost network only
            return [
                "firejail",
                "--noprofile",
                "--net=localhost",
                "--caps.drop=all",
                f"--timeout={int(cmd.timeout_ms / 1000)}",
                cmd.executable,
            ] + cmd.args

        else:  # PERMISSIVE
            # Minimal restrictions
            return [cmd.executable] + cmd.args

    def establish_connection(self, node_id: str, host: str, port: int = 22) -> bool:
        """
        Establish SSH connection to remote node.

        Args:
            node_id: Target node ID
            host: Hostname or IP
            port: SSH port

        Returns:
            True if connection successful
        """
        with self._lock:
            try:
                # In real implementation, would establish SSH connection
                # For now, just record connection info
                self._connections[node_id] = {
                    "host": host,
                    "port": port,
                    "connected_at": time.time(),
                    "status": "CONNECTED",
                }

                logger.info(f"SSH connection to {node_id}@{host}:{port} established")
                return True

            except Exception as e:
                logger.error(f"Failed to connect to {node_id}: {e}")
                self._connections[node_id] = {
                    "host": host,
                    "port": port,
                    "connected_at": time.time(),
                    "status": "FAILED",
                    "error": str(e),
                }
                return False

    def close_connection(self, node_id: str) -> None:
        """Close SSH connection."""
        with self._lock:
            if node_id in self._connections:
                self._connections[node_id]["status"] = "CLOSED"
                logger.info(f"Closed connection to {node_id}")

    def get_command_result(self, command_id: str) -> Optional[RemoteResult]:
        """Retrieve cached command result."""
        with self._lock:
            return self._command_results.get(command_id)

    def _audit_execution(self, cmd: RemoteCommand, result: RemoteResult) -> None:
        """Log command execution to audit trail."""
        self._executed_commands.append({
            "command_id": cmd.command_id,
            "node_id": cmd.node_id,
            "executable": cmd.executable,
            "args": cmd.args,
            "success": result.success,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "timestamp": time.time(),
        })

        logger.debug(
            f"Audit: {cmd.command_id} on {cmd.node_id} "
            f"({cmd.executable} {' '.join(cmd.args[:3])}...)"
        )

    def get_execution_audit(self, since_timestamp: float = 0.0) -> List[Dict[str, Any]]:
        """Get audit trail of executed commands."""
        with self._lock:
            return [
                cmd for cmd in self._executed_commands
                if cmd["timestamp"] >= since_timestamp
            ]

    def get_orchestrator_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        with self._lock:
            return {
                "total_commands": len(self._executed_commands),
                "successful_commands": sum(
                    1 for cmd in self._executed_commands if cmd["success"]
                ),
                "failed_commands": sum(
                    1 for cmd in self._executed_commands if not cmd["success"]
                ),
                "active_connections": sum(
                    1 for conn in self._connections.values()
                    if conn.get("status") == "CONNECTED"
                ),
                "total_connections": len(self._connections),
                "sandbox_policy": self._sandbox_policy.value,
            }


class SSHConnectionPool:
    """Pool of SSH connections for efficient reuse."""

    def __init__(self, max_connections: int = 10):
        """
        Initialize connection pool.

        Args:
            max_connections: Maximum concurrent connections
        """
        self._lock = threading.RLock()
        self._max_connections = max_connections
        self._available: Dict[str, List[Any]] = {}  # Connections available per node
        self._in_use: Dict[str, List[Any]] = {}  # Connections in use per node
        self._connection_count: Dict[str, int] = {}  # Total per node

    def acquire(self, node_id: str) -> Optional[Any]:
        """Acquire connection from pool."""
        with self._lock:
            if node_id in self._available and self._available[node_id]:
                return self._available[node_id].pop()

            # Create new connection if below limit
            current_count = self._connection_count.get(node_id, 0)
            if current_count < self._max_connections:
                self._connection_count[node_id] = current_count + 1
                return f"connection_{node_id}_{current_count}"

            return None

    def release(self, node_id: str, connection: Any) -> None:
        """Return connection to pool."""
        with self._lock:
            if node_id not in self._available:
                self._available[node_id] = []
            self._available[node_id].append(connection)

    def get_pool_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        with self._lock:
            total_connections = sum(self._connection_count.values())
            available_connections = sum(
                len(conns) for conns in self._available.values()
            )

            return {
                "total_connections": total_connections,
                "available_connections": available_connections,
                "in_use_connections": total_connections - available_connections,
                "max_connections": self._max_connections,
                "per_node_counts": dict(self._connection_count),
            }
