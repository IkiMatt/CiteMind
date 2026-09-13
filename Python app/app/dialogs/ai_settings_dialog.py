"""
ai_settings_dialog.py — Backward-compatible wrapper.

All AI settings are now managed by SettingsDialog.
This module re-exports the static helpers so that existing
imports throughout the codebase continue to work without changes.
"""
from app.dialogs.settings_dialog import SettingsDialog


class AiSettingsDialog:
    """Thin compatibility shim — delegates to SettingsDialog."""

    SETTINGS_URL = SettingsDialog.SETTINGS_URL
    SETTINGS_MODEL = SettingsDialog.SETTINGS_MODEL
    SETTINGS_SEMANTIC_MODEL = SettingsDialog.SETTINGS_SEMANTIC_MODEL
    SETTINGS_API_KEY = SettingsDialog.SETTINGS_API_KEY

    _DEFAULT_URL = SettingsDialog._DEFAULT_URL
    _DEFAULT_MODEL = SettingsDialog._DEFAULT_MODEL

    get_ai_provider = staticmethod(SettingsDialog.get_ai_provider)
    get_ollama_url = staticmethod(SettingsDialog.get_ollama_url)
    get_model_name = staticmethod(SettingsDialog.get_model_name)
    get_semantic_model_name = staticmethod(SettingsDialog.get_semantic_model_name)
    get_api_key = staticmethod(SettingsDialog.get_api_key)
