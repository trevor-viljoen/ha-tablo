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
| `button.<name>_stop_live_tv` | Stops every live TV stream this integration started |
| `select.<name>_live_tv_channel` | Channel picker used by `tablo.watch_channel` when no channel is given |

Polls every 60 seconds.

## Live TV

The Tablo streams MPEG-2, which browsers and Chromecast can't decode. To play on those, run [tablo-web](https://github.com/trevor-viljoen/tablo-web) and set its URL under **Settings → Devices & services → Tablo → Configure**. Streams then go through tablo-web and are transcoded to H.264. A stream takes about 10 seconds to start.

**Media panel:** channels show up under **Media → Tablo**. Pick a player at the bottom of the panel, then a channel. This works for browsers and most players.

**Apple TV:** not supported. Home Assistant's Apple TV integration plays Media panel items as audio only. On tvOS 26 and later, sending a stream URL over AirPlay opens the Apple TV's player but it never loads the stream. Use the Tablo app on the Apple TV. The integration refuses Apple TV targets rather than tying up a tuner.

**Other players** (browsers, Chromecast, Kodi and so on) can also be targeted with the `tablo.watch_channel` action:

```yaml
action: tablo.watch_channel
data:
  entity_id: media_player.living_room_chromecast
  channel: "5.1"   # number, call sign, or name; omit to use the channel picker
```

A dashboard button for each TV only needs `entity_id`. Pair it with the **Live TV channel** picker.

The integration stops each transcoded stream it started when:

- the player doesn't start playing within 45 seconds;
- the player turns off or goes idle;
- the player stays paused for 10 minutes;
- you play another channel on the same player (there is one stream per player, so double taps are safe);
- the stream has been running for 8 hours;
- you press **Stop live TV**.

Without a tablo-web URL, players get the Tablo's raw MPEG-2 stream.

## Install

**HACS:** add this repository as a custom repository (category *Integration*), install **Tablo**, then restart Home Assistant.

**Manual:** copy `custom_components/tablo` into your Home Assistant `config/custom_components/` folder, then restart Home Assistant.

Then go to **Settings → Devices & services → Add integration → Tablo** and enter the Tablo's IP address. The port is `8887` on 4th Gen devices.

## Notes

- Tested with a Tablo 4G QUAD 128GB on firmware 2.2.58.
- 2nd/3rd Gen Tablos use a different, unauthenticated API and aren't supported.
- Related: [tablo-api](https://github.com/trevor-viljoen/tablo-api) (cloud login, channel list, live streams).

## Roadmap

- Play recordings from the media source
- Recording management services (schedule, delete)

---

## Support & Donations

If you find this project useful and would like to support its development, you can buy me a coffee!

[![PayPal](https://img.shields.io/badge/PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/trevorviljoen)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsors-EA4AAA?style=for-the-badge&logo=github-sponsors&logoColor=white)](https://github.com/sponsors/trevor-viljoen)

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

> Tablo and the Tablo logo are trademarks of Nuvyyo Inc. This project is not affiliated with or endorsed by Nuvyyo.
