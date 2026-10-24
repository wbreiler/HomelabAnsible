#!/bin/bash
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
test "$(uname -s)" = Darwin
test "$(uname -m)" = x86_64
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"
git init -q
git -c user.name=Smoke -c user.email=smoke@example.invalid commit --allow-empty -qm smoke
git fsck --no-progress
node -e 'if (process.arch !== "x64") process.exit(1); console.log("Node execution OK")'
npm --version
uv run --python 3.13 --no-project python -c 'import ssl, sqlite3; print("Python SSL and SQLite OK")'
printf '#include <stdio.h>\nint main(void){puts("C compiler OK");return 0;}\n' > main.c
clang main.c -o hello
./hello
printf '#include <iostream>\nint main(){std::cout << "C++17 compiler OK\\n";}\n' > main.cpp
clang++ -std=c++17 main.cpp -o hello-cpp
./hello-cpp
printf 'cmake_minimum_required(VERSION 3.20)\nproject(smoke C)\nadd_executable(hello main.c)\n' > CMakeLists.txt
cmake -S . -B build -G Ninja >/dev/null
cmake --build build
./build/hello
git-lfs version
gh --version | head -1
ansible --version | head -1
ansible-lint --version
"$HOME/.local/share/uv/tools/ansible-core/bin/python" -c 'import proxmoxer, requests; print("Ansible Proxmox dependencies OK")'
printf 'Development host smoke test passed\n'
