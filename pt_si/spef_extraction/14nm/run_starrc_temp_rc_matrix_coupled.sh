#!/usr/bin/env bash
set -euo pipefail

# Site-specific inputs come from environment variables (no hardcoded paths/licenses).
#   PROJ_ROOT            : project root that contains deliverables/14nm/... (required)
#   PDK_ROOT             : dir holding the layer map + corners files (default: <base>/pdk)
#   STARRC_ROOT          : StarRC install root (default: /usr/synopsys/starrc/<ver>)
#   SNPSLMD_LICENSE_FILE : Synopsys license (port@host) - must be set in the environment
proj_root="${PROJ_ROOT:?set PROJ_ROOT to the project root (…/deliverables lives under it)}"
base="${proj_root}/deliverables/14nm"
pdk_root="${PDK_ROOT:-${base}/pdk}"
corners_file="${STARRC_CORNERS_FILE:-${pdk_root}/corners_beol_14nm_temp_rc_matrix.corners}"
mapping_file="${STARRC_MAPPING_FILE:-${pdk_root}/saed14nm_1p9m_ndm_layer.map}"
starrc_root="${STARRC_ROOT:?set STARRC_ROOT to the StarRC install root}"
export STARRC="${starrc_root}"
: "${SNPSLMD_LICENSE_FILE:?set SNPSLMD_LICENSE_FILE (port@host) in your environment}"
export SNPSLMD_LICENSE_FILE
starxtract="${STARRC_BIN:-${starrc_root}/bin/StarXtract}"
output_tag="${STARRC_OUTPUT_TAG:-starrc_temp_rc_matrix_20260618}"
parallel_jobs="${STARRC_JOBS:-1}"

default_corners=(
  Cmin_model_m40 Cnom_model_m40 Cmax_model_m40
  Cmin_model_25 Cnom_model_25 Cmax_model_25
  Cmin_model_125 Cnom_model_125 Cmax_model_125
)

is_complete_spef() {
  local spef="$1"
  [[ -s "${spef}" ]] || return 1
  grep -q '^\*PROGRAM "StarRC"' "${spef}" || return 1
  grep -q '^\*END' "${spef}" || return 1
}

spef_matches_corner() {
  local spef="$1"
  local corner="$2"
  local expected_grid expected_temp actual_grid actual_temp

  case "${corner}" in
    Cmin_*) expected_grid="Cmin" ;;
    Cnom_*) expected_grid="nominal" ;;
    Cmax_*) expected_grid="Cmax" ;;
    *)
      echo "Unknown corner for SPEF validation: ${corner}" >&2
      return 1
      ;;
  esac

  case "${corner}" in
    *_m40) expected_temp="-40" ;;
    *_25) expected_temp="25" ;;
    *_125) expected_temp="125" ;;
    *)
      echo "Unknown temperature suffix for SPEF validation: ${corner}" >&2
      return 1
      ;;
  esac

  actual_temp="$(head -n 80 "${spef}" | sed -n 's#^// OPERATING_TEMPERATURE ##p' | head -n 1)"
  actual_grid="$(head -n 80 "${spef}" | sed -n 's#^// TCAD_GRD_FILE ##p' | head -n 1)"

  if [[ "${actual_temp}" != "${expected_temp}" ]]; then
    echo "SPEF corner mismatch: ${spef} ${corner} expected temp ${expected_temp}, got ${actual_temp}" >&2
    return 1
  fi

  if [[ "${actual_grid}" != *"${expected_grid}"* ]]; then
    echo "SPEF corner mismatch: ${spef} ${corner} expected grid ${expected_grid}, got ${actual_grid}" >&2
    return 1
  fi
}

is_valid_spef_for_corner() {
  local spef="$1"
  local corner="$2"
  is_complete_spef "${spef}" || return 1
  spef_matches_corner "${spef}" "${corner}" || return 1
}

run_design() {
  local design="$1"
  local block="$2"
  local lib_name="$3"
  local tag="$4"
  local prefix="$5"
  shift 5

  local proc_dir="${base}/processors/${design}"
  local run_root="${proc_dir}/icc2/result/${tag}"
  local lib_path="${proc_dir}/icc2/${lib_name}"
  local base_output_dir="${run_root}/outputs"
  local output_dir="${base_output_dir}/${output_tag}"
  local cmd_dir="${run_root}/starrc_cmds/${output_tag}"
  local star_root="${run_root}/starrc/${output_tag}"

  for required in "${corners_file}" "${mapping_file}" "${lib_path}" "${run_root}" "${base_output_dir}" "${starxtract}"; do
    if [[ ! -e "${required}" ]]; then
      echo "Missing required path: ${required}" >&2
      return 2
    fi
  done

  mkdir -p "${output_dir}" "${cmd_dir}" "${star_root}"

  local corners=("$@")
  if [[ "${#corners[@]}" -eq 0 ]]; then
    corners=("${default_corners[@]}")
  fi

  for corner in "${corners[@]}"; do
    local cmd="${cmd_dir}/${prefix}.starrc_coupled.${corner}.cmd"
    local log="${run_root}/starrc_coupled_${output_tag}_${corner}.log"
    local out_rel="outputs/${output_tag}/${prefix}.starrc_coupled.${corner}.spef"
    local out_abs="${output_dir}/${prefix}.starrc_coupled.${corner}.spef"
    local netlist_rel="${out_rel}"
    local netlist_abs="${out_abs}"
    local star_dir="${star_root}/star_coupled_${corner}"

    # BoomCoreV3/large runs can leave a zero-byte suffix SPEF when StarRC writes
    # directly into a nested output directory. Write to outputs/ first, then move.
    if [[ "${design}" == "BoomCoreV3" ]]; then
      netlist_rel="outputs/${prefix}.starrc_coupled.${corner}.${output_tag}.spef"
      netlist_abs="${base_output_dir}/${prefix}.starrc_coupled.${corner}.${output_tag}.spef"
    fi

    if is_valid_spef_for_corner "${out_abs}" "${corner}" && [[ "${FORCE_STARRC:-0}" != "1" ]]; then
      echo "===== ${design} ${corner} coupled ====="
      echo "Existing coupled StarRC SPEF found, skipping: ${out_abs}"
      echo "Set FORCE_STARRC=1 to re-run this corner."
      continue
    elif [[ -e "${out_abs}" && "${FORCE_STARRC:-0}" != "1" ]]; then
      echo "===== ${design} ${corner} coupled ====="
      echo "Existing SPEF is incomplete or non-StarRC, rerunning: ${out_abs}"
    fi

    cat > "${cmd}" <<EOF
* Auto-generated SAED14nm coupled StarRC extraction for ${design} ${corner}.
* User-guide RCC equivalent:
*   EXTRACTION: RC
*   COUPLE_TO_GROUND: NO
* Coupling thresholds are set to zero so coupling capacitors are retained.
* Run from: ${run_root}

BLOCK: ${block}
NDM_DATABASE: ${lib_path}
MAPPING_FILE: ${mapping_file}
CORNERS_FILE: ${corners_file}
SELECTED_CORNERS: ${corner}
SIMULTANEOUS_MULTI_CORNER: NO
STAR_DIRECTORY: ${star_dir}
EXTRACTION: RC
NETS: *
NETLIST_FORMAT: SPEF
NETLIST_FILE: ${netlist_rel}
COUPLE_TO_GROUND: NO
COUPLING_ABS_THRESHOLD: 0
COUPLING_REL_THRESHOLD: 0
XREF: NO
EOF

    echo "===== ${design} ${corner} coupled ====="
    echo "Command: ${cmd}"
    echo "Log: ${log}"
    if [[ "${STARRC_STREAM_LOGS:-0}" == "1" ]]; then
      (
        cd "${run_root}"
        "${starxtract}" -clean "${cmd}"
      ) 2>&1 | tee "${log}"
    else
      (
        cd "${run_root}"
        "${starxtract}" -clean "${cmd}"
      ) > "${log}" 2>&1
    fi

    for candidate in "${netlist_abs}" "${netlist_abs}.${corner}" "${out_abs}.${corner}"; do
      if [[ "${candidate}" != "${out_abs}" ]] && is_complete_spef "${candidate}"; then
        mv "${candidate}" "${out_abs}"
        break
      fi
    done

    if ! is_valid_spef_for_corner "${out_abs}" "${corner}"; then
      echo "Expected coupled StarRC SPEF was not created: ${out_abs}" >&2
      return 3
    fi
    echo "Done: ${out_abs}"
  done
}

run_one() {
  local design="$1"
  shift || true
  case "${design}" in
    ibex)
      run_design ibex ibex_core ibex_14nm_tt0p8v25c_ccs_clk1520_icc2_lib ibex_14nm_tt0p8v25c_ccs_clk1520 ibex_14nm "$@"
      ;;
    RocketCore)
      run_design RocketCore Rocket rocket_14nm_tt0p8v25c_ccs_clk1720_icc2_lib rocket_14nm_tt0p8v25c_ccs_clk1720 rocket_14nm "$@"
      ;;
    SmallBoomV2)
      run_design SmallBoomV2 BoomCore smallboom_14nm_tt0p8v25c_ccs_clk2820_icc2_lib smallboom_14nm_tt0p8v25c_ccs_clk2820 smallboom_14nm "$@"
      ;;
    BoomCoreV3)
      run_design BoomCoreV3 BoomCore boomcorev3_14nm_tt0p8v25c_ccs_clk1020_icc2_lib boomcorev3_14nm_tt0p8v25c_ccs_clk1020 boomcorev3_14nm "$@"
      ;;
    *)
      echo "Unknown design '${design}'. Use one of: ibex RocketCore SmallBoomV2 BoomCoreV3" >&2
      return 2
      ;;
  esac
}

usage() {
  cat <<EOF
Usage:
  $0 [-j jobs] [design ...]
  $0 [-j jobs] --corner <corner> [design ...]

Designs: ibex RocketCore SmallBoomV2 BoomCoreV3
Default corners: ${default_corners[*]}
Output tag: ${output_tag}
Set FORCE_STARRC=1 to overwrite existing outputs in this output tag.
Set STARRC_STREAM_LOGS=1 to stream each StarRC log to stdout.
EOF
}

run_tasks_parallel() {
  local jobs="$1"
  shift
  local active=0
  local failed=0

  for task in "$@"; do
    local design="${task%%:*}"
    local corner="${task#*:}"

    (
      run_one "${design}" "${corner}"
    ) &

    active=$((active + 1))
    if (( active >= jobs )); then
      if ! wait -n; then
        failed=1
      fi
      active=$((active - 1))
    fi
  done

  while (( active > 0 )); do
    if ! wait -n; then
      failed=1
    fi
    active=$((active - 1))
  done

  return "${failed}"
}

run_designs_parallel() {
  local jobs="$1"
  shift
  local active=0
  local failed=0

  for design in "$@"; do
    (
      run_one "${design}"
    ) &

    active=$((active + 1))
    if (( active >= jobs )); then
      if ! wait -n; then
        failed=1
      fi
      active=$((active - 1))
    fi
  done

  while (( active > 0 )); do
    if ! wait -n; then
      failed=1
    fi
    active=$((active - 1))
  done

  return "${failed}"
}

args=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    -j|--jobs)
      if [[ "$#" -lt 2 ]]; then
        usage >&2
        exit 2
      fi
      parallel_jobs="$2"
      shift 2
      ;;
    --jobs=*)
      parallel_jobs="${1#*=}"
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done
set -- "${args[@]}"

if ! [[ "${parallel_jobs}" =~ ^[0-9]+$ ]] || (( parallel_jobs < 1 )); then
  echo "Invalid jobs value: ${parallel_jobs}" >&2
  exit 2
fi

if [[ "$#" -eq 0 ]]; then
  set -- ibex RocketCore SmallBoomV2 BoomCoreV3
fi

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "$1" == "--corner" ]]; then
  if [[ "$#" -lt 2 ]]; then
    usage >&2
    exit 2
  fi
  corner="$2"
  shift 2
  if [[ "$#" -eq 0 ]]; then
    set -- ibex RocketCore SmallBoomV2 BoomCoreV3
  fi
  if (( parallel_jobs == 1 )); then
    for design in "$@"; do
      run_one "${design}" "${corner}"
    done
  else
    tasks=()
    for design in "$@"; do
      tasks+=("${design}:${corner}")
    done
    run_tasks_parallel "${parallel_jobs}" "${tasks[@]}"
  fi
else
  if (( parallel_jobs == 1 )); then
    for design in "$@"; do
      run_one "${design}"
    done
  else
    echo "Running designs in parallel and corners serially per design to avoid same-run-root StarRC corner races."
    run_designs_parallel "${parallel_jobs}" "$@"
  fi
fi
