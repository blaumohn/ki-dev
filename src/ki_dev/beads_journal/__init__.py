"""Beads-Journal: je bd-Ereignis ein Commit in ein lokales Git-Repo.

Die versionierten Hooks .beads/hooks/on_create|on_update|on_close rufen
``python -m ki_dev.beads_journal hook ID EREIGNIS`` mit dem Issue-JSON
auf stdin auf. Aktiv ist das Journal nur, wenn sein Ordner den Marker
.beads-journal trägt (eingerichtet mit ``init``).
"""
