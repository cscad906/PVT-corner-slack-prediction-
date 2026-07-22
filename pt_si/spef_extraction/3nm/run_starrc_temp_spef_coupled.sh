#!/usr/bin/env bash
set -euo pipefail

# Site-specific inputs come from environment variables (no hardcoded paths/PDK names).
# See ../README.md. Required: PROJ_ROOT, PDK_LAYER_MAP, PDK_NXTGRD (+ StarXtract on PATH,
# and SNPSLMD_LICENSE_FILE in your environment).
base="${PROJ_ROOT:?set PROJ_ROOT to the project root (…/deliverables lives under it)}/deliverables/3nm"
bundle="${base}/spice_deck_bundle"
mapping_file="${PDK_LAYER_MAP:?set PDK_LAYER_MAP to the StarRC layer-mapping file}"
nxtgrd_file="${PDK_NXTGRD:?set PDK_NXTGRD to the StarRC grid (.nxtgrd) file}"

force=0

usage() {
  cat <<'EOF'
Usage:
  run_starrc_temp_spef_coupled.sh [--force] [design ...]

Designs:
  BoomCoreV3 RocketCore SmallBoomV2 ibex

The script extracts explicit-coupling StarRC SPEFs with COUPLE_TO_GROUND: NO
and copies them into spice_deck_bundle/processors/<design>/deliver using the
existing temperature SPEF filenames.
EOF
}

cap_count() {
  local f="$1"
  awk '
    BEGIN { cap=0; c=0 }
    /^\*CAP/ { cap=1; next }
    /^\*RES|^\*END|^\*CONN|^\*D_NET/ { cap=0 }
    cap && $1 ~ /^[0-9]+$/ && NF==4 { c++ }
    END { print c }
  ' "${f}"
}

run_design() {
  local design="$1"
  local block="$2"
  local lib_name="$3"
  local tag="$4"
  local file_stem="$5"
  local netlist_stem="$6"
  shift 6

  local proc_dir="${base}/processors/${design}"
  local run_root="${proc_dir}/icc2/result/${tag}"
  local lib_path="${proc_dir}/icc2/${lib_name}"
  local deliver_dir="${bundle}/processors/${design}/deliver"
  local work_dir="${run_root}/coupled_outputs"
  local cmd_dir="${run_root}/starrc_cmds"
  local star_root="${run_root}/starrc"
  local corners_file="${cmd_dir}/${file_stem}_temp_coupled.corners"
  local cmd="${cmd_dir}/${file_stem}_temp_coupled.cmd"
  local log="${run_root}/starrc_temp_coupled.log"
  local out_prefix="${work_dir}/${netlist_stem}.spef"
  local selected_corners=()

  for required in "${mapping_file}" "${nxtgrd_file}" "${lib_path}" "${run_root}" "${deliver_dir}"; do
    if [[ ! -e "${required}" ]]; then
      echo "Missing required path: ${required}" >&2
      return 2
    fi
  done

  mkdir -p "${work_dir}" "${cmd_dir}" "${star_root}"
  : > "${corners_file}"

  local spec label temp corner deliver_file src_file
  for spec in "$@"; do
    label="${spec%%:*}"
    temp="${spec#*:}"
    corner="temp_${label}"
    selected_corners+=("${corner}")
    deliver_file="${deliver_dir}/${file_stem}_${label}.spef"

    if [[ ! -e "${deliver_file}" ]]; then
      echo "Missing deliver SPEF target for ${design} ${label}: ${deliver_file}" >&2
      return 2
    fi

    cat >> "${corners_file}" <<EOF
CORNER_NAME: ${corner}
TCAD_GRD_FILE: ${nxtgrd_file}
OPERATING_TEMPERATURE: ${temp}

EOF
  done

  cat > "${cmd}" <<EOF
* Auto-generated 3nm explicit-coupling StarRC extraction for ${design}.
* Run from: ${run_root}

BLOCK: ${block}
NDM_DATABASE: ${lib_path}
MAPPING_FILE: ${mapping_file}

CORNERS_FILE: ${corners_file}
SELECTED_CORNERS: ${selected_corners[*]}
SIMULTANEOUS_MULTI_CORNER: YES

STAR_DIRECTORY: ${star_root}/star_temp_coupled_all
NETLIST_FORMAT: SPEF
NETLIST_FILE: ${out_prefix}

EXTRACTION: RC
COUPLE_TO_GROUND: NO
NETLIST_TYPE: RCc
COUPLING_ABS_THRESHOLD: 0
COUPLING_REL_THRESHOLD: 0

XREF: NO
EOF

  local have_all=1
  for spec in "$@"; do
    label="${spec%%:*}"
    corner="temp_${label}"
    src_file="${out_prefix}.${corner}"
    if [[ ! -s "${src_file}" ]]; then
      have_all=0
      break
    fi
  done

  if [[ "${force}" -eq 1 || "${have_all}" -eq 0 ]]; then
    echo "===== ${design} explicit-coupling temperature SPEF extraction ====="
    echo "Command: ${cmd}"
    echo "Log: ${log}"
    (
      cd "${run_root}"
      StarXtract -clean "${cmd}"
    ) 2>&1 | tee "${log}"
  else
    echo "===== ${design} explicit-coupling temperature SPEF extraction ====="
    echo "Existing coupled outputs found, skipping StarRC run."
  fi

  for spec in "$@"; do
    label="${spec%%:*}"
    corner="temp_${label}"
    src_file="${out_prefix}.${corner}"
    deliver_file="${deliver_dir}/${file_stem}_${label}.spef"

    if [[ ! -s "${src_file}" ]]; then
      echo "Expected coupled SPEF was not created: ${src_file}" >&2
      return 3
    fi

    cp -p "${src_file}" "${deliver_file}"
    local coupling
    coupling="$(cap_count "${deliver_file}")"
    if [[ "${coupling}" -le 0 ]]; then
      echo "Copied SPEF has no explicit coupling entries: ${deliver_file}" >&2
      return 4
    fi
    printf "%s\t%s\tcoupling_cap_entries=%s\t%s\n" "${design}" "${label}" "${coupling}" "${deliver_file}"
  done
}

run_one() {
  case "$1" in
    BoomCoreV3)
      run_design BoomCoreV3 BoomCore boomcorev3_phig_u0_ns boomcorev3_TT_0p7V_25C_clk10 boomcorev3 boomcorev3_temp_coupled \
        m40:-40 m25:-25 25:25 50:50 70:70 85:85 100:100 125:125
      ;;
    RocketCore)
      run_design RocketCore Rocket rocket_phig_u0_ns rocket_TT_0p7V_25C_clk0980 rocket rocket_temp_coupled \
        m40:-40 m25:-25 25:25 70:70 85:85 125:125
      ;;
    SmallBoomV2)
      run_design SmallBoomV2 BoomCore smallboom_phig_u0_ns smallboom_TT_0p7V_25C_clk10 smallboom smallboom_temp_coupled \
        m40:-40 m25:-25 25:25 70:70 85:85 125:125
      ;;
    ibex)
      run_design ibex ibex_core ibex_phig_u0_ns ibex_TT_0p7V_25C_clk1020 ibex ibex_core_temp_coupled \
        m40:-40 m25:-25 25:25 70:70 85:85 125:125
      ;;
    *)
      echo "Unknown design '$1'. Use one of: BoomCoreV3 RocketCore SmallBoomV2 ibex" >&2
      return 2
      ;;
  esac
}

designs=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --force)
      force=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      designs+=("$1")
      ;;
  esac
  shift
done

if [[ "${#designs[@]}" -eq 0 ]]; then
  designs=(ibex RocketCore SmallBoomV2 BoomCoreV3)
fi

for design in "${designs[@]}"; do
  run_one "${design}"
done
