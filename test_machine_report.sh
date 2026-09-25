#!/usr/bin/env bash
# Run on a Linux host with the report script in the same directory.
set -euo pipefail
cd "$(dirname "$0")"
if [[ ${1:-} == - ]]; then
    report=$(cat)
else
    report=$(bash machine_report.sh)
fi
width=''
while IFS= read -r row; do
    if [[ -z $width ]]; then width=${#row}; fi
    [[ ${#row} -eq $width ]] || { printf 'Uneven report row: %s\n' "$row" >&2; exit 1; }
done <<< "$report"
[[ $report == *'│ ROOT         │ '*' GiB ('* ]]
[[ $report == *'│ MEMORY       │ '*' GiB ('* ]]
[[ $report == *'│ LOAD 1/5/15m │ '* ]]
[[ -z ${REPORT_EXPECT_IP:-} || $report == *"│ IP           │ $REPORT_EXPECT_IP"* ]]
[[ -z ${REPORT_EXPECT_CORES:-} || $report == *"│ CORES        │ $REPORT_EXPECT_CORES CPU(s)"* ]]
printf 'Report rows aligned; root, memory, and load populated.\n'
