# Minecraft tick-performance report

**Active-play rerun:** October 22, 2026, 22:34:54–22:39:54 CDT. UTC: 2026-10-23 03:34:54–03:39:54.

## Summary

All five instances still run on **Atlas** in unprivileged LXCs. Direct systemd Java services confirm no Docker or VM layer. Atlas reports dual Xeon Gold 6248 CPUs. Prometheus reports dual E5-2697A v4 CPUs and hosts none of these instances.

**Hewwo-pwincess had one player at all 11 polls.** The user confirmed active play. This is an ordinary-play sample, with player-driven chunk generation unverified. Native Overall TPS displayed 13.607–20.000. Sampled rolling mean tick times were **20.889–73.494 ms/tick**, versus **4.921–5.445** during the earlier idle sample. The other four instances remained empty and inconclusive for loaded performance.

**Four new lag warnings** occurred during the window. A healthy displayed TPS does not exclude intermittent lag. Standard 20-TPS operation allows **50 ms per tick**. A server can sustain 20 TPS with limited headroom. [Spark explanation](https://spark.lucko.me/docs/guides/TPS-and-MSPT).

## Runtime and allocation

RAM, heap, and RSS use GiB. Heap shows configured Xms/Xmx, not actual occupancy. CPUs are allowed logical CPUs, not dedicated cores. All guests expose the physical Gold 6248 CPU model, without VM emulation.

| Instance | CT / host | Minecraft / loader | Java | CPUs / RAM | Heap | Final RSS |
|---|---|---|---|---|---|---:|
| atm10-nash | 113 / Atlas | 1.21.1 / NeoForge 21.1.259 | GraalVM CE 21.0.2 | 4 / 16 | 2G / 12G | 9.42 |
| homestead-nash | 115 / Atlas | 1.20.1 / Fabric 0.18.4 | Temurin 17.0.20.1+1 | 3 / 10 | 2G / 8G | 4.43 |
| yabu-nash | 116 / Atlas | 26.3 / Fabric 0.19.5 | GraalVM CE 25.0.2 | 3 / 10 | 2G / 8G | 2.37 |
| bettermc-nash | 120 / Atlas | 1.20.1 / Forge 47.4.20 | Temurin 17.0.20.1+1 | 4 / 18 | 2G / 12G | 7.74 |
| hewwo-pwincess | 124 / Atlas | 1.21.1 / NeoForge 21.1.259 | GraalVM CE 21.0.2 | 6 / 24 | 2G / 22G | 12.14 |

Hewwo-pwincess's installed and running pack markers both identify [ATM10 8.3](https://www.curseforge.com/minecraft/modpacks/all-the-mods-10/files/9190157). Cobbleverse CT 114 remains absent from the live cluster.

All containers retain unlimited CPU quota (`cpu.max = max 100000`) and weight 100. Quota throttling did not increase. Host memory limits match the allocations above. Each container has 512 MiB configured swap. Java swap use stayed zero.

| Instance | Effective CPU affinity | Allowed memory nodes | Final resident pages N0 / N1 |
|---|---|---|---|
| atm10-nash | `5,7,20-21` | `0-1` | 9.1% / 90.9% |
| homestead-nash | `11-12,24` | `0-1` | 91.1% / 8.9% |
| yabu-nash | `3,13-14` | `0-1` | 5.0% / 95.0% |
| bettermc-nash | `16-19` | `0-1` | 75.3% / 24.7% |
| hewwo-pwincess | `0,2,4,6,8,10` | `0` | 100.0% / 0.0% |

Atlas maps even CPUs to node 0 and odd CPUs to node 1. Hewwo-pwincess explicitly uses six distinct physical cores and memory on node 0. Others span both nodes. Affinity does not establish exclusive core ownership. Page placement does not measure remote-memory access rates.

## Tick measurements

All timestamps below are UTC. Hewwo-pwincess values come from the native `neoforge tps` Overall line. Every other instance reported zero players at these same polls. Their TPS/MSPT remain unavailable because RCON is disabled.

| UTC | Hewwo players | Displayed Overall TPS | Overall mean ms/tick | Main runnable wait, preceding interval |
|---|---:|---:|---:|---:|
| 03:34:54 | 1 | 20.000 | 21.486 | — |
| 03:35:24 | 1 | 20.000 | 23.030 | 0.30% |
| 03:35:54 | 1 | 20.000 | 26.562 | 0.27% |
| 03:36:24 | 1 | 20.000 | 20.889 | 0.05% |
| 03:36:54 | 1 | unavailable (RCON timeout) | unavailable | 0.17% |
| 03:37:24 | 1 | 20.000 | 41.286 | 7.46% |
| 03:37:54 | 1 | 13.607 | 73.494 | 11.63% |
| 03:38:24 | 1 | 20.000 | 38.875 | 13.26% |
| 03:38:54 | 1 | 20.000 | 28.190 | 4.07% |
| 03:39:24 | 1 | 20.000 | 43.338 | 4.77% |
| 03:39:54 | 1 | 15.574 | 64.212 | 12.92% |

One RCON request timed out. Its tick values are unavailable. Successful responses are rolling means with an unlabeled window, not individual tick samples. NeoForge derives displayed TPS from mean tick time, capped at the configured rate. [Command source](https://raw.githubusercontent.com/neoforged/NeoForge/1.21.1/src/main/java/net/neoforged/neoforge/server/command/TPSCommand.java).

**Individual-tick median, p95, p99, maximum, and frequency above 50 ms are unavailable for every instance.** No percentiles were calculated from averages. Lag warnings measure accumulated delay, not individual tick durations or counts above 50 ms.

Hewwo-pwincess's DH controller recorded paused pre-generation. Its supported status command reported no active pre-generation. Chunky's controller recorded completion. Player exploration could still generate chunks. No new pre-generation progress appeared in the examined logs. Yabu retains a 60-second idle-pause setting, consistent with its near-zero main CPU use.

## Correlation and observed limits

**One logical CPU = 100%.** The highest interval is a 30-second average, not an instantaneous peak. Runnable wait shows main-thread scheduler delay per elapsed time.

| Instance | Main CPU mean | Highest 30-second mean | Main runnable wait | CPU pressure, some | I/O pressure, some |
|---|---:|---:|---:|---:|---:|
| atm10-nash | 1.76% | 2.13% | 0.001% | 0.02% | 0.00% |
| homestead-nash | 3.79% | 4.40% | 0.026% | 1.09% | 0.00% |
| yabu-nash | 0.02% | 0.03% | 0.000% | 0.02% | 0.00% |
| bettermc-nash | 1.51% | 2.23% | 0.003% | 1.45% | 0.00% |
| hewwo-pwincess | 54.83% | 72.57% | 5.493% | 7.65% | 0.03% |

Hewwo-pwincess's earlier idle main CPU averaged **13.12%**. This run averaged **54.83%**. The increase confirms greater main-thread work. It does not identify the cause of each lag event.

Atlas averaged 4.61% CPU busy across 80 logical CPUs, 0.03% I/O wait, and 0.00% steal. CPU pressure covered 6.87% of elapsed time. Low total utilization does not establish main-thread headroom. Bare-metal steal does not measure LXC scheduling contention. Quota counters show no throttling. Main-thread runnable wait increased, so scheduling contention warrants attention despite low host-wide CPU use.

| Backing device | Read/write operations | Full-window mean request await | Device busy |
|---|---:|---:|---:|
| sdc | 16174 | 1.253 ms | 5.712% |
| sdd | 16157 | 0.4 ms | 1.695% |
| sdh | 16498 | 0.355 ms | 1.487% |
| sdi | 16043 | 0.412 ms | 1.74% |

Disk means include other host activity and can conceal latency spikes. They cannot establish the disk latency of a slow tick. GC pause telemetry remains unavailable. Inspected locations contain no usable GC logs. No JVM attachment or new telemetry was enabled. Existing Spark RCON responses were incomplete during the earlier run. This run reused the working native command.

| Lag warning, CDT | Reported accumulated delay | Reported ticks behind |
|---|---:|---:|
| 22:35:47 | 2,175 ms | 43 |
| 22:37:00 | 13,914 ms | 278 |
| 22:37:49 | 2,365 ms | 47 |
| 22:39:53 | 2,022 ms | 40 |

The server exceeded its tick budget during ordinary play. The 73.494 ms/tick poll followed an interval with 11.63% main-thread runnable wait. The next interval reached 13.26%. Scheduling pressure accompanied the slowdown, but this does not establish its full cause. Mod activity, competing workloads, GC, disk spikes, and chunk generation remain unresolved.

## Method, limitations, and next step

1. Used existing authorized SSH, live Proxmox placement, LXC limits, systemd cgroups, Java metadata, and launcher versions. No credentials or raw logs are included.
2. Collected 11 polls, 30 seconds apart, over five minutes. Server status supplied counts without player names. Native TPS supplied rolling means.
3. Differenced main-thread CPU/scheduler counters, container pressure, host CPU counters, and backing disk counters. Timestamps mark poll starts. Counter intervals are approximate because responses take time. Polling misses short events and adds minor overhead.
4. Read only. No installations, restarts, settings changes, profiler, chunk generation, or synthetic load occurred. Other machines were not exhaustively scanned.
5. Compared against the earlier idle window. This single-player sample does not establish multiplayer capacity or exact Gold 6154-versus-6248 performance. No Gold 6154 was measured.

**Next:** capture the existing Spark summary through an authorized operator session during ordinary play, near a lag event. Obtain actual per-tick data before reporting tail percentiles. Compare similar natural workloads on the candidate host before making a hardware decision.
