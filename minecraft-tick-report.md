# Minecraft tick-performance report

Collection: October 22, 2026, 22:12:50–22:17:50 CDT. UTC: October 23, 03:12:50–03:17:50.

## Summary

All five instances run directly under systemd in unprivileged LXCs on **Atlas**. None use Docker or a VM. Live host CPU models confirmed dual Gold 6248 on Atlas and dual E5-2697A v4 on Prometheus. Prometheus hosted none of these instances.

All five reported **zero players at all 11 polls**. This idle sample is inconclusive for loaded performance. No active chunk generation was established. Hewwo-pwincess reported native Overall TPS of 20.000 throughout. Its sampled rolling mean tick times ranged from **4.921 to 5.445 ms/tick**. Four instances lacked an accessible tick-metric channel. No tick bottleneck was established.

Standard 20-TPS operation has a **50 ms tick budget**. A server can maintain 20 TPS with little remaining headroom. Average TPS and low total CPU usage can conceal slow individual ticks or main-thread saturation. [Spark explanation](https://spark.lucko.me/docs/guides/TPS-and-MSPT).

## Per-instance runtime and allocation

RAM, heap, and RSS use GiB. Heap shows configured initial/maximum sizes, not occupancy. CPUs are logical allocations, not dedicated cores. Every guest reported Gold 6248, with no emulated CPU model.

| Instance | CT | Host | Minecraft / implementation | Java runtime | CPUs | RAM | Heap Xms / Xmx | Final JVM RSS |
|---|---:|---|---|---|---:|---:|---|---:|
| atm10-nash | 113 | Atlas | 1.21.1 / NeoForge 21.1.259 | GraalVM CE 21.0.2 | 4 | 16 | 2 / 12 | 9.42 |
| homestead-nash | 115 | Atlas | 1.20.1 / Fabric 0.18.4 | Temurin 17.0.20.1+1 | 3 | 10 | 2 / 8 | 4.43 |
| yabu-nash | 116 | Atlas | 26.3 / Fabric 0.19.5 | GraalVM CE 25.0.2 | 3 | 10 | 2 / 8 | 2.37 |
| bettermc-nash | 120 | Atlas | 1.20.1 / Forge 47.4.20 | Temurin 17.0.20.1+1 | 4 | 18 | 2 / 12 | 7.74 |
| hewwo-pwincess | 124 | Atlas | 1.21.1 / NeoForge 21.1.259 | GraalVM CE 21.0.2 | 6 | 24 | 2 / 22 | 10.83 |

Cobbleverse-nash remains in the local inventory, but CT 114 was absent from the live cluster. It was not measured or assumed to run elsewhere.

### CPU limits, affinity, and NUMA

All LXCs had unlimited CPU quota (`cpu.max = max 100000`), weight 100, and zero additional quota throttling. The parent cgroup had no quota. Host memory limits matched the allocations above. Each LXC had 512 MiB configured swap. Java swap use stayed zero.

| Instance | Effective host CPU affinity | Allowed memory nodes | Final resident pages N0 / N1 |
|---|---|---|---|
| atm10-nash | `5,7,20-21` | `0-1` | 9.1% / 90.9% |
| homestead-nash | `11-12,24` | `0-1` | 91.8% / 8.2% |
| yabu-nash | `3,13-14` | `0-1` | 5.1% / 94.9% |
| bettermc-nash | `16-19` | `0-1` | 81.9% / 18.1% |
| hewwo-pwincess | `0,2,4,6,8,10` | `0` | 100.0% / 0.0% |

Atlas maps even CPU numbers to node 0 and odd numbers to node 1. Hewwo-pwincess explicitly uses node 0 and six distinct physical cores. Others span both nodes. Page placement does not measure remote-access rates. Affinity does not prove exclusive core ownership.

## Tick measurements

All player counts were zero at every timestamp. TPS and MSPT are **unavailable** for atm10-nash, homestead-nash, yabu-nash, and bettermc-nash.

Hewwo-pwincess returned the following native `neoforge tps` Overall values:

| UTC timestamp, October 23 | Players | Displayed Overall TPS | Overall mean ms/tick |
|---|---:|---:|---:|
| 03:12:50 | 0 | 20.000 | 5.148 |
| 03:13:20 | 0 | 20.000 | 5.120 |
| 03:13:50 | 0 | 20.000 | 4.934 |
| 03:14:20 | 0 | 20.000 | 5.014 |
| 03:14:50 | 0 | 20.000 | 4.921 |
| 03:15:20 | 0 | 20.000 | 5.355 |
| 03:15:50 | 0 | 20.000 | 5.445 |
| 03:16:20 | 0 | 20.000 | 5.109 |
| 03:16:50 | 0 | 20.000 | 5.000 |
| 03:17:20 | 0 | 20.000 | 5.008 |
| 03:17:50 | 0 | 20.000 | 5.170 |

These are sampled rolling means, not individual tick durations or five-minute percentiles. The command does not label its averaging window. NeoForge calculates displayed TPS from mean tick time, capped at the configured tick rate. It is not an independent tick-counter measurement. [NeoForge command source](https://raw.githubusercontent.com/neoforged/NeoForge/1.21.1/src/main/java/net/neoforged/neoforge/server/command/TPSCommand.java).

**Median, p95, p99, maximum individual tick time, and frequency above 50 ms: unavailable for every instance.** No actual per-tick series was collected. None of the available rolling means exceeded 50 ms. That does not establish that every individual tick met its budget.

Yabu configured idle pause after 60 seconds. Its near-zero main CPU is consistent with pause, but not direct proof. Hewwo-pwincess recorded completed DH and Chunky controllers. DH status confirmed no active pre-generation. Chunky progress was unavailable. Examined logs showed no additional pre-generation or lag warnings. Brief or unlogged work remains possible.

## CPU, contention, GC, and disk correlation

**One logical CPU = 100%.** The highest interval is a 30-second average, not a peak. Runnable wait shows main-thread scheduler delay per elapsed time.

| Instance | Main CPU mean | Highest 30-second main CPU mean | Main runnable wait | LXC CPU pressure, some | LXC I/O pressure, some |
|---|---:|---:|---:|---:|---:|
| atm10-nash | 1.92% | 2.33% | 0.002% | 0.04% | 1.13% |
| homestead-nash | 2.97% | 3.13% | 0.038% | 1.23% | 0.06% |
| yabu-nash | 0.03% | 0.03% | 0.000% | 0.04% | 0.07% |
| bettermc-nash | 1.28% | 1.63% | 0.012% | 1.24% | 0.03% |
| hewwo-pwincess | 13.12% | 13.73% | 0.034% | 0.37% | 0.05% |

Atlas averaged 1.62% busy across 80 logical CPUs, 0.11% I/O wait, and 0.00% steal. CPU pressure covered 0.48% of elapsed time. Host I/O pressure covered 0.95%. These host averages cannot demonstrate main-thread headroom. Bare-metal host steal also does not measure LXC scheduler contention. The main-thread wait counters provide the more relevant contention evidence here.

The four backing block devices reported these full-window means from kernel disk counters:

| Device | Completed reads + writes | Mean request await | Device busy time |
|---|---:|---:|---:|
| sdc | 18539 | 0.247 ms | 1.166% |
| sdd | 20084 | 0.379 ms | 2.069% |
| sdh | 21626 | 0.221 ms | 1.219% |
| sdi | 17807 | 0.389 ms | 1.926% |

Device means include other host activity. They do not measure tick I/O latency. Some container stalls occurred, without a measurable slow-tick correlation. ZFS pools were online without reported data errors.

GC correlation was unavailable. Inspected locations exposed no GC logs or JVM performance counters. No JVM attachment or new logging was used. Spark RCON responses were empty or incomplete and were discarded. No per-tick series supports CPU, GC, or disk correlation. **No loaded bottleneck is established.**

## Collection method and limitations

1. Used existing agent-backed SSH, Proxmox cluster resources, live LXC configuration, and direct process cgroups. Placement was verified twice.
2. Polled all five instances 11 times, 30 seconds apart, over 300 seconds. Existing Java server status supplied versions and player counts.
3. Read executable release metadata, JVM arguments, Fabric launcher metadata, startup version matches, affinity, NUMA maps, and kernel counters. Systemd cgroups confirmed direct Java services.
4. Used existing RCON credentials locally without exposing them. Server help confirmed `neoforge tps`. Spark was installed on four instances, but only Hewwo-pwincess had enabled RCON.
5. Recorded selected operational counters instead of raw logs. No credentials, player names, addresses, or chat are included. The report covers the discovered Proxmox instances, not an exhaustive network scan.

Observation commands contribute some CPU and I/O overhead. Preliminary discovery and incomplete Spark collection preceded this window. No installation, service restart, setting change, profiler, chunk generation, or synthetic load occurred.

## Gold 6154 decision and smallest next step

This idle sample does not establish loaded suitability for a Gold 6154. Neither Prometheus workloads nor a Gold 6154 were measured. No exact 6154-versus-6248 difference follows.

Next: capture existing Spark TPS summaries through an authorized operator session during ordinary play. No installation is necessary. Four instances lack an enabled remote tick channel. No setting was changed. Compare similar normal-play measurements on the candidate host. Obtain actual tick samples before calculating percentiles or ticks above 50 ms.
