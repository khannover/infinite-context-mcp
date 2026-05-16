from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import Lock


def _default_state() -> dict[str, object]:
    return {"private": {}, "shared": {}}


def _normalize_visibility(visibility: str) -> str:
    if visibility not in {"private", "shared"}:
        raise ValueError("Visibility must be 'private' or 'shared'")
    return visibility


class ContextStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = Lock()
        self._state = self._load()

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return _default_state()
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", delete=False, dir=self.path.parent, encoding="utf-8"
        ) as handle:
            json.dump(self._state, handle, sort_keys=True, indent=2)
            temp_name = handle.name
        os.replace(temp_name, self.path)

    def upsert(
        self,
        *,
        agent_id: str,
        visibility: str,
        space: str,
        key: str,
        value: object,
    ) -> dict[str, object]:
        with self._lock:
            resolved_visibility = _normalize_visibility(visibility)
            if resolved_visibility == "shared":
                namespace = self._state["shared"]
            else:
                namespace = self._state["private"].setdefault(agent_id, {})
            namespace.setdefault(space, {})[key] = value
            self._save()
            return {
                "visibility": resolved_visibility,
                "space": space,
                "key": key,
                "value": value,
            }

    def get(
        self, *, agent_id: str, visibility: str, space: str, key: str
    ) -> dict[str, object] | None:
        with self._lock:
            resolved_visibility = _normalize_visibility(visibility)
            namespace = (
                self._state["shared"]
                if resolved_visibility == "shared"
                else self._state["private"].get(agent_id, {})
            )
            value = namespace.get(space, {}).get(key)
            if value is None and key not in namespace.get(space, {}):
                return None
            return {
                "visibility": resolved_visibility,
                "space": space,
                "key": key,
                "value": value,
            }

    def list_accessible(self, *, agent_id: str) -> dict[str, object]:
        with self._lock:
            return {
                "private": self._state["private"].get(agent_id, {}),
                "shared": self._state["shared"],
            }

    def change_visibility(
        self,
        *,
        agent_id: str,
        from_visibility: str,
        to_visibility: str,
        space: str,
        key: str,
        target_space: str,
        remove_source: bool,
    ) -> dict[str, object]:
        with self._lock:
            resolved_from_visibility = _normalize_visibility(from_visibility)
            resolved_to_visibility = _normalize_visibility(to_visibility)
            source_namespace = (
                self._state["shared"]
                if resolved_from_visibility == "shared"
                else self._state["private"].get(agent_id, {})
            )
            if key not in source_namespace.get(space, {}):
                raise KeyError(
                    f"Context '{key}' was not found in {resolved_from_visibility}:{space}"
                )
            value = source_namespace[space][key]
            destination_namespace = (
                self._state["shared"]
                if resolved_to_visibility == "shared"
                else self._state["private"].setdefault(agent_id, {})
            )
            destination_namespace.setdefault(target_space, {})[key] = value
            if remove_source:
                del source_namespace[space][key]
                if not source_namespace[space]:
                    del source_namespace[space]
            self._save()
            return {
                "key": key,
                "value": value,
                "from_visibility": resolved_from_visibility,
                "to_visibility": resolved_to_visibility,
                "space": space,
                "target_space": target_space,
                "remove_source": remove_source,
            }

    def delete(
        self,
        *,
        agent_id: str,
        visibility: str,
        space: str,
        key: str,
    ) -> dict[str, object]:
        with self._lock:
            resolved_visibility = _normalize_visibility(visibility)
            namespace = (
                self._state["shared"]
                if resolved_visibility == "shared"
                else self._state["private"].get(agent_id, {})
            )
            if key not in namespace.get(space, {}):
                raise KeyError(f"Context '{key}' was not found in {resolved_visibility}:{space}")
            value = namespace[space][key]
            del namespace[space][key]
            if not namespace[space]:
                del namespace[space]
            self._save()
            return {
                "visibility": resolved_visibility,
                "space": space,
                "key": key,
                "value": value,
                "deleted": True,
            }

    def list_all_entries(self) -> list[dict[str, object]]:
        with self._lock:
            entries: list[dict[str, object]] = []
            for agent_id, spaces in self._state["private"].items():
                for space, items in spaces.items():
                    for key, value in items.items():
                        entries.append(
                            {
                                "visibility": "private",
                                "agent_id": agent_id,
                                "space": space,
                                "key": key,
                                "value": value,
                            }
                        )
            for space, items in self._state["shared"].items():
                for key, value in items.items():
                    entries.append(
                        {
                            "visibility": "shared",
                            "agent_id": None,
                            "space": space,
                            "key": key,
                            "value": value,
                        }
                    )
            return entries
