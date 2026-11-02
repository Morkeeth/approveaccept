#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
out_dir=${1:-"$repo_dir/../capture"}

python3 -B -m unittest -q test_spend_rules test_build
node design/check-tokens.cjs
node design/check-contrast.cjs
node design/check-stamps.cjs index.html ''
python3 "$repo_dir/../../demo-rig/demorig.py" approveaccept --out "$out_dir" --res both --only A
