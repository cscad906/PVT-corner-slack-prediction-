#!/usr/bin/env bash
set -euo pipefail

# Site-specific inputs come from environment variables (no hardcoded paths/licenses).
# See ../README.md for the full list. Required: PROJ_ROOT, STARRC_ROOT, SNPSLMD_LICENSE_FILE.
proj_root="${PROJ_ROOT:?set PROJ_ROOT to the project root (…/deliverables lives under it)}"
base="${proj_root}/deliverables/14nm"
pdk_root="${PDK_ROOT:-${base}/pdk}"
corners_file="${STARRC_CORNERS_FILE:-${pdk_root}/corners_beol_14nm_25c.corners}"
mapping_file="${STARRC_MAPPING_FILE:-${pdk_root}/saed14nm_1p9m_ndm_layer.map}"
starrc_root="${STARRC_ROOT:?set STARRC_ROOT to the StarRC install root}"
export STARRC="${starrc_root}"
: "${SNPSLMD_LICENSE_FILE:?set SNPSLMD_LICENSE_FILE (port@host) in your environment}"
export SNPSLMD_LICENSE_FILE
starxtract="${STARRC_BIN:-${starrc_root}/bin/StarXtract}"

run_design() {
  local design="$1"
  local block="$2"
  local lib_name="$3"
  local tag="$4"
  local prefix="$5"

  local proc_dir="${base}/processors/${design}"
  local run_root="${proc_dir}/icc2/result/${tag}"
  local lib_path="${proc_dir}/icc2/${lib_name}"
  local output_dir="${run_root}/outputs"
  local cmd_dir="${run_root}/starrc_cmds"
  local star_root="${run_root}/starrc"

  for required in "${corners_file}" "${mapping_file}" "${lib_path}" "${run_root}" "${output_dir}" "${starxtract}"; do
    if [[ ! -e "${required}" ]]; then
      echo "Missing required path: ${required}" >&2
      return 2
    fi
  done

  mkdir -p "${cmd_dir}" "${star_root}"

  local corners=("$@")
  corners=("${corners[@]:5}")
  if [[ "${#corners[@]}" -eq 0 ]]; then
    corners=(Cnom_model_25 Cmin_model_25 Cmax_model_25)
  fi

  for corner in "${corners[@]}"; do
    local cmd="${cmd_dir}/${prefix}.starrc_coupled.${corner}.cmd"
    local log="${run_root}/starrc_coupled_${corner}.log"
    local out_rel="outputs/${prefix}.starrc_coupled.${corner}.spef"
    local out_abs="${output_dir}/${prefix}.starrc_coupled.${corner}.spef"
    local star_dir="${star_root}/star_coupled_${corner}"

    if [[ -s "${out_abs}" ]]; then
      echo "===== ${design} ${corner} coupled ====="
      echo "Existing coupled StarRC SPEF found, skipping: ${out_abs}"
      continue
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
NETLIST_FILE: ${out_rel}
COUPLE_TO_GROUND: NO
COUPLING_ABS_THRESHOLD: 0
COUPLING_REL_THRESHOLD: 0
XREF: NO
EOF

    echo "===== ${design} ${corner} coupled ====="
    echo "Command: ${cmd}"
    echo "Log: ${log}"
    (
      cd "${run_root}"
      "${starxtract}" -clean "${cmd}"
    ) 2>&1 | tee "${log}"

    if [[ ! -s "${out_abs}" && -s "${out_abs}.${corner}" ]]; then
      mv "${out_abs}.${corner}" "${out_abs}"
    fi

    if [[ ! -s "${out_abs}" ]]; then
      echo "Expected coupled StarRC SPEF was not created: ${out_abs}" >&2
      return 3
    fi
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

if [[ "$#" -eq 0 ]]; then
  set -- ibex RocketCore SmallBoomV2 BoomCoreV3
fi

if [[ "$1" == "--corner" ]]; then
  if [[ "$#" -lt 3 ]]; then
    echo "Usage: $0 --corner <corner> [design ...]" >&2
    exit 2
  fi
  corner="$2"
  shift 2
  for design in "$@"; do
    run_one "${design}" "${corner}"
  done
else
  for design in "$@"; do
    run_one "${design}"
  done
fi
