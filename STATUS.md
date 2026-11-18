# Status

## 2026-11-17: rework (v2)

- Rebuilt around one installer for Paper or Fabric, one manager process
  (Discord bot plus idle shutdown), Modrinth mod/plugin lists, clean RCON stop
  and nightly backups. Removed multi-instance support, Logfire and the
  benchmarking tools; the old state is on branch `archive/2026-09-pi-state`.
- Verified on pi1 in a throwaway checkout: Fabric 26.3 with the default
  performance mods boots in about 40 s on first run and uses about 1.1 GiB
  idle. RCON, backups, clean stop, installer reruns, `--new-world` and the
  server-type guard all worked.
- Not yet done: cutover of the live services on pi1, the group's mod list,
  pregeneration, and the 8-player load test.
