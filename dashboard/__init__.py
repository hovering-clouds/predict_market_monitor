"""Dashboard package for arbitrage monitoring UI and backend."""

from .server import create_app, MonitorManager

__all__ = ["create_app", "MonitorManager"]
