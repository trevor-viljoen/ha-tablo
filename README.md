# Tablo for Home Assistant

Unofficial Home Assistant integration for the **Tablo 4th Gen** OTA DVR (Nuvyyo / LighthouseTV).

It talks to the Tablo's local API only. Requests are HMAC-signed with the same static keys the Tablo app uses, so **no Tablo account login is needed** and nothing goes through the cloud.

## Entities

| Entity | Description |
|---|---|
| `binary_sensor.<name>_recording` | On while any tuner is recording |
| `sensor.<name>_tuners_in_use` | Tuners currently in use (attribute: total tuners) |
| `sensor.<name>_recordings` | Number of recordings on the device |
| `sensor.<name>_scheduled_recordings` | Number of upcoming scheduled airings |
| `sensor.<name>_next_recording` | Start time of the next scheduled recording (attributes: title, episode, channel) |
| `sensor.<name>_storage_free` / `_storage_used` / `_storage_size` | Storage stats |
| `calendar.<name>_scheduled_recordings` | Upcoming scheduled recordings as calendar events |

Polls every 60 seconds.

## Install

**HACS:** add this repository as a custom repository (category *Integration*), install **Tablo**, then restart Home Assistant.

**Manual:** copy `custom_components/tablo` into your Home Assistant `config/custom_components/` folder, then restart Home Assistant.

Then go to **Settings → Devices & services → Add integration → Tablo** and enter the Tablo's IP address. The port is `8887` on 4th Gen devices.

## Notes

- Tested with a Tablo 4G QUAD 128GB on firmware 2.2.58.
- 2nd/3rd Gen Tablos use a different, unauthenticated API and aren't supported.
- Related: [tablo-api](https://github.com/trevor-viljoen/tablo-api) (cloud login, channel list, live streams).

## Roadmap

- Media source: browse channels and recordings, and play them on a media player
- Recording management services (schedule, delete)
