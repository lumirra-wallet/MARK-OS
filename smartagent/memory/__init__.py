"""
Memory subpackage.

Responsible for storing and retrieving everything SmartAgent needs to
remember: conversation history, learned facts, user preferences, etc.
The goal is to support multiple interchangeable backends (in-memory,
SQLite, a vector store for semantic search) behind one consistent
interface, `MemoryManager`.
"""
