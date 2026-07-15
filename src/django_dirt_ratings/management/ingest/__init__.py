"""Ingest domain package (manage-only).

All heavy neuroimaging imports live under here, not under ``commands/`` — Django
autodiscovers only ``management/commands/``, so importing a spec's neuro stack
never happens for the web runtime. The single ``render`` command drives this
package; ``orchestrator.ingest_dataset`` is the entry point.
"""
