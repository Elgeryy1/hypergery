"""HyperGery v0.9/v1.0 services.

Everything in this package follows the same rules as the rest of HyperGery:
no destructive defaults (dry-run first), no secrets, structured logging, and
clear errors. Services degrade gracefully when the Hub, the NAS, or a remote
host is unavailable.
"""
