"""
Models subpackage.

Wraps the language model backend(s) SmartAgent reasons with, behind a
single `ModelClient` interface. Keeping this separate from `brain` means
the orchestration logic never depends on a specific provider (OpenAI,
Anthropic, a local model, etc.) — swapping backends should only require
changes here.
"""
