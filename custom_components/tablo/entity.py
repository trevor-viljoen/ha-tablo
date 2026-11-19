"""Base entity for Tablo."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TabloCoordinator


class TabloEntity(CoordinatorEntity[TabloCoordinator]):
    """Common device info and unique-id handling."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TabloCoordinator, key: str) -> None:
        super().__init__(coordinator)
        info = coordinator.data.info
        server_id = info["server_id"]
        model = info.get("model") or {}
        self._attr_unique_id = f"{server_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, server_id)},
            name=info.get("name") or "Tablo",
            manufacturer="Nuvyyo",
            model=model.get("name") or model.get("type"),
            model_id=model.get("type"),
            serial_number=server_id,
            sw_version=info.get("version"),
            configuration_url=f"http://{info.get('local_address')}:8887/server/info"
            if info.get("local_address")
            else None,
        )
