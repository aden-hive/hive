"""
Kubernetes Cluster Analyzer Tool - Inspect pods, deployments, and cluster events.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

try:
    from kubernetes import client, config
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False

if TYPE_CHECKING:
    from aden_tools.credentials.store_adapter import CredentialStoreAdapter

def _get_kubeconfig(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("kubernetes")
    return os.getenv("KUBECONFIG")

def _init_client(kubeconfig_path: str | None) -> dict[str, Any] | None:
    if not K8S_AVAILABLE:
        return {"error": "kubernetes python package is not installed."}

    try:
        if kubeconfig_path and os.path.exists(kubeconfig_path):
            config.load_kube_config(config_file=kubeconfig_path)
        else:
            config.load_kube_config()
        return None
    except Exception as e:
        return {"error": f"Failed to initialize Kubernetes client: {str(e)}"}

def register_tools(mcp: FastMCP, credentials: CredentialStoreAdapter | None = None) -> None:
    """Register Kubernetes tools with the MCP server."""

    @mcp.tool()
    def kubernetes_list_pods(namespace: str = "default") -> dict[str, Any]:
        """List pods in a specific Kubernetes namespace to check cluster health."""
        kubeconfig = _get_kubeconfig(credentials)
        err = _init_client(kubeconfig)
        if err:
            return err

        try:
            v1 = client.CoreV1Api()
            pods = v1.list_namespaced_pod(namespace)
            result = [
                {
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "ip": pod.status.pod_ip,
                    "node": pod.spec.node_name
                }
                for pod in pods.items
            ]
            return {"namespace": namespace, "pods": result, "total": len(result)}
        except Exception as e:
            return {"error": f"Kubernetes API error: {str(e)}"}
