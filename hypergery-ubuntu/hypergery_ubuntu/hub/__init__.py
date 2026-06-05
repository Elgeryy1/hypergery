from __future__ import annotations

from ..registry import ALLOWED_COMMAND_TYPES, RegistryClient, RegistryServer, RegistryStore, serve_registry

HubClient = RegistryClient
HubServer = RegistryServer
HubStore = RegistryStore
serve_hub = serve_registry

__all__ = [
    "ALLOWED_COMMAND_TYPES",
    "HubClient",
    "HubServer",
    "HubStore",
    "serve_hub",
]
