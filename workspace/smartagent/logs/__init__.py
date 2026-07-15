"""
Logs subpackage.

Centralizes logging setup so every other subpackage can `get_logger(...)`
instead of configuring `logging` (or printing) independently. This is
infrastructure, not a feature: it does not change SmartAgent's observable
behavior, it just gives the growing codebase one consistent place to
control log format/level/output.
"""
