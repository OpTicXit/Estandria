"""Limpieza de estilo: sugerencias de redacción deterministas que el autor acepta o rechaza una a una."""
from app.style.rules import Hallazgo, analyze, detect_language
from app.style.text_model import ReviewText, apply_findings

__all__ = ["Hallazgo", "ReviewText", "analyze", "apply_findings", "detect_language"]
