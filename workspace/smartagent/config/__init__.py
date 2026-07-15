"""
Configuration subpackage.

Centralizes all settings for SmartAgent (API keys, model choices, feature
flags, file paths, etc.) so the rest of the codebase never reads environment
variables or config files directly. Everything should flow through
`Settings`.
"""
