"""Internal split of ``bridge.database`` (issue #1305 demote-split).

This subpackage holds the implementation of the ``Database`` class — split
into three cohesive mixins:

* ``connection.py`` — async SQLite connection lifecycle + per-statement
  execute/fetch helpers.
* ``migrations.py`` — schema DDL constants, versioned migration runner,
  schema-version tracking.
* ``queries.py`` — DB-level maintenance helpers (backup, integrity check,
  rotation). Per the issue body, the slot was named "queries"; in practice
  ``bridge.database`` itself has no per-table CRUD (those helpers live in
  caller modules like ``bridge.memory``, ``bridge.session_manager``). The
  module name is preserved for spec parity with the umbrella issue.

External callers should continue to import from ``bridge.database`` — this
subpackage is an implementation detail.
"""
