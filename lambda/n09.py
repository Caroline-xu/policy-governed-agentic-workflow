"""N09 Lambda entry point (thin wrapper over shared.node_base)."""
from shared.node_base import make_handler

handler = make_handler("N09")
