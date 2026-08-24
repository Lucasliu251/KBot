# QQMusicApi vendored source

- Upstream: https://github.com/L-1124/QQMusicApi
- Version: 0.7.2
- Commit: `108617ffe80abefec6358717b9f4d3677550db10`
- License: GNU General Public License v3.0 or later; see `LICENSE` in this directory.

Only the importable `qqmusic_api` package is vendored. KBot's adapter lives in
`MusicBot/qqmusic_service.py`; upstream source is kept separate so it can be audited
or replaced without mixing provider-specific details into the player.
