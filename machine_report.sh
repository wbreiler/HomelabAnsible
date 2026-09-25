#!/usr/bin/env bash
# TR-100 Machine Report
# Copyright © 2024, U.S. Graphics, LLC. BSD-3-Clause License.

export LC_ALL=C.UTF-8

if [[ ${1:-} == --ascii ]]; then
    exec > >(sed 's/[┌┬┐├┴┤┼└┘]/+/g; s/─/-/g; s/│/|/g')
fi

line() { local i; for ((i=0; i<$1; i++)); do printf '%s' "$2"; done; }
top() { printf '┌%s┐\n' "$(line 51 '─')"; }
divider() { printf '├%s┼%s┤\n' "$(line 14 '─')" "$(line 36 '─')"; }
bottom() { printf '└%s┴%s┘\n' "$(line 14 '─')" "$(line 36 '─')"; }
row() { printf '│ %-12.12s │ %-34.34s │\n' "$1" "$2"; }

volume() {
    awk -v used="$1" -v total="$2" 'BEGIN {
        unit = "GiB"; size = 1073741824
        if (total >= 1099511627776) { unit = "TiB"; size = 1099511627776 }
        printf "%.2f/%.2f %s (%.1f%%)", used/size, total/size, unit,
            (total > 0 ? used/total*100 : 0)
    }'
}

# Read local host facts. The script runs on Linux hosts, including TrueNAS SCALE.
source /etc/os-release
host=$(hostname -f 2>/dev/null || hostname)
host=${host%.}
read -r client_ip _ machine_ip _ <<< "${SSH_CONNECTION:-}"
if [[ -z $machine_ip ]]; then
    machine_ip=$(ip -o -4 addr show scope global 2>/dev/null |
        awk '$2 !~ /^(docker|veth|br-|virbr)/ {split($4, a, "/"); print a[1]; exit}')
fi
machine_ip=${machine_ip:-Unavailable}
client_ip=${client_ip:-Not\ connected}

platform=''
if command -v pveversion >/dev/null 2>&1; then
    platform="Proxmox $(pveversion 2>/dev/null | cut -d/ -f2)"
elif command -v midclt >/dev/null 2>&1; then
    platform=$(timeout 8 midclt call system.version 2>/dev/null | tr -d '\"')
    platform=${platform:-TrueNAS}
fi

cpu_model=$(lscpu | awk -F: '/^Model name:/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}' |
    sed -E 's/\(R\)//g; s/ CPU / /; s/ @.*//')
cpu_sockets=$(lscpu | awk -F: '/^Socket\(s\):/ {gsub(/[[:space:]]/, "", $2); print $2; exit}')
cpu_cores=$(nproc --all)
cpu_freq=$(awk -F: '/^cpu MHz/ {printf "%.2f", $2 / 1000; exit}' /proc/cpuinfo)
read -r load_1 load_5 load_15 _ < /proc/loadavg

read -r mem_total mem_available < <(awk '
    /^MemTotal:/ {total=$2}
    /^MemAvailable:/ {available=$2}
    END {print total, available}
' /proc/meminfo)
mem_used=$((mem_total - mem_available))
memory=$(awk -v used="$mem_used" -v total="$mem_total" 'BEGIN {
    printf "%.2f/%.2f GiB (%.1f%%)", used/1048576, total/1048576,
        (total > 0 ? used/total*100 : 0)
}')

read -r root_total root_used < <(df -Pk / | awk 'NR==2 {print $2, $3}')
root_volume=$(volume "$((root_used * 1024))" "$((root_total * 1024))")

zfs_pools=''
if command -v zpool >/dev/null 2>&1; then
    zfs_pools=$(timeout 8 zpool list -Hp -o name,size,alloc,health 2>/dev/null)
fi

last_login_time=Unavailable
last_login_ip=''
for login_command in lastlog2 lastlog; do
    command -v "$login_command" >/dev/null 2>&1 || continue
    login=$($login_command -u "$(id -un)" 2>/dev/null) || continue
    [[ -n $login ]] && break
done
if [[ ${login:-} == *'Never logged in'* ]]; then
    last_login_time='Never logged in'
elif [[ -n ${login:-} ]]; then
    read -r last_login_time last_login_ip < <(printf '%s\n' "$login" | awk 'NR==2 {
        ip=""
        for (i=2; i<=NF; i++) {
            if ($i ~ /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$/) {
                printf "%s_%s_%s_%s %s\n", $(i+1), $(i+2), $(i+5), $(i+3), ip
                exit
            }
            if ($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ || $i ~ /:/) ip=$i
        }
    }')
    last_login_time=${last_login_time//_/ }
    last_login_time=${last_login_time:-Unavailable}
fi
uptime=$(uptime -p | sed 's/^up //; s/ days\?/d/g; s/ hours\?/h/g; s/ minutes\?/m/g')

top
printf '│ %-49s │\n' 'CLUSTER-NASH - TR-100 MACHINE REPORT'
divider
row 'OS' "${PRETTY_NAME:-Linux}"
row 'KERNEL' "$(uname -sr)"
[[ -n $platform ]] && row 'PLATFORM' "$platform"
row 'HOST' "$host"
row 'IP' "$machine_ip"
row 'CLIENT' "$client_ip"
divider
row 'CPU' "$cpu_model"
row 'CORES' "$cpu_cores CPU(s) / ${cpu_sockets:-?} socket(s) / ${cpu_freq:-?} GHz"
row 'LOAD 1/5/15m' "$load_1 / $load_5 / $load_15"
divider
row 'ROOT' "$root_volume"
if [[ -n $zfs_pools ]]; then
    while read -r pool_name pool_size pool_used pool_health; do
        case "$pool_name" in rpool|boot-pool|bpool) continue ;; esac
        row "ZFS $pool_name" "$(volume "$pool_used" "$pool_size") [$pool_health]"
    done <<< "$zfs_pools"
fi
row 'MEMORY' "$memory"
divider
row 'LOGIN' "$last_login_time"
[[ -n $last_login_ip ]] && row 'LOGIN IP' "$last_login_ip"
row 'UPTIME' "$uptime"
bottom
