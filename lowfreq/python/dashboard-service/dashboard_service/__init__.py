"""Dashboard.Service package marker.

Importable as `dashboard_service` so `uvicorn dashboard_service.main:app`
works when the package is on PYTHONPATH (k8s container installs it via
the Dockerfile COPY; local dev runs from this directory).
"""
__version__ = "1.0.0"
