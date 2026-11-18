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

## 2026-11-17: pi1 cutover and load test

- pi1 now runs Fabric 26.3 from `~/pi-minecraft-server` with the group's mods
  (66 mod components including libraries), offline mode, hard difficulty, and
  the old ops/whitelist/bans. The old Paper 26.2 world stays in `~/Minecraft`,
  with a final backup in `~/Minecraft/backups/`.
- Regression checks passed: start through the `!up` sudo rule (ready in ~33 s,
  ~1.2 GiB), idle shutdown with Discord notice, `systemctl stop` saving through
  RCON, start at boot after a reboot, backup timer active.
- Load test with 8 Carpet fake players (spectators, so no mob spawning):
  standing in generated terrain averaged ~13 ms per tick (p95 ~18 ms), well
  within 50 ms. Exploring new terrain in 8 directions at once averaged ~18 ms
  but had frequent 0.3-1.1 s tick spikes, with ~3 of 4 cores busy. Memory peaked
  at ~2.7 GiB of the 4 GiB heap limit. The Pi reached 85 C and throttled even
  with the fan running; it idles at 64-66 C.
- Next: pregenerate the world before inviting players, and improve cooling.

## 2026-11-17: pregeneration, FallingTree, local mod lists

- Pregenerated the pi1 world with Chunky: 1,500-block circle around spawn,
  35,721 chunks in 9 min 11 s, peak 84 C.
- Mod and plugin lists are now local, untracked files (`mods.txt`,
  `plugins.txt`) created from `mods.example.txt` / `plugins.example.txt`, so
  the shared repo only suggests server-side defaults. Backups include them.
  pi1's list holds the group's mods plus FallingTree.
