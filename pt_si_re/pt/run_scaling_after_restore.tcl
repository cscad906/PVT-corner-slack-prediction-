# PrimeTime restore_session 직후 실행하는 독립형 scaling 스크립트
#
# 사용 순서:
#   pt_shell
#   restore_session /path/to/saved_session
#   아래 USER SETTINGS를 실제 실행 조건에 맞게 수정
#   source /home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/pt/run_scaling_after_restore.tcl
#
# 현재 restore session에 이미 로드된 design/library/SDC/SPEF만 사용합니다.
# 이 파일은 read_db/read_verilog/link_design/read_sdc/read_parasitics를 실행하지 않습니다.
# 현재 활성 parasitic의 BEOL/온도가 목표와 일치할 때만 scaling을 실행합니다.
# source하면 아래 설정을 검사한 뒤 scaling을 바로 시작합니다.

# ======================= USER SETTINGS ========================
set TARGET_PROCESS      "SSPG"
set TARGET_VOLTAGE      0.75
set TARGET_TEMPERATURE  25
set TARGET_BEOL         "rcmax"
set SCALING_AXIS        "V"       ;# V, T, VT
set ANALYSIS            "setup"   ;# setup 또는 hold

set FIXED_PATH_FILE "fixed_paths.tcl"
set RESULT_FOLDER   "auto_scaling_output"

# 긴 작업의 진행 상황 출력 간격(분). 계산 결과에는 영향을 주지 않습니다.
set PROGRESS_INTERVAL_MINUTES 10

# target voltage를 적용할 확실한 실제 supply net 하나만 입력하십시오.
# restore session에서 조회된 나머지 supply net은 모두 자동으로 fixed 처리됩니다.
set SCALING_POWER_NET "" ;# target voltage 적용 rail

# 고정 경로에서 VDDPE scaling할 셀 이름 또는 연결된 library 이름을 지정합니다.
# * 와 ? 사용 가능. 여러 패턴은 쉼표로 구분: "*u_mem*,*sram*"
# 빈칸이면 VDDPE macro scaling을 사용하지 않습니다.
set VDDPE_SCALING_NAME_PATTERNS "*u_mem*"
# 선택된 셀이 있을 때 목표 VDDPE 전압을 입력하십시오. 코어 TARGET_VOLTAGE와
# 다를 수 있습니다. 공급 net 전체의 전압은 변경하지 않습니다.
set TARGET_VDDPE_VOLTAGE ""

# Optional: keep selected sets at their restored DB/conditions, without interpolation.
# Enter an exact set name, a common pattern such as "macro_*", or names/patterns
# separated by spaces. Empty disables this option. "restore" never relinks
# cells or applies target V/T to these sets. Explicit "nearest" picks the loaded
# DB closest to TARGET_VOLTAGE at the same process/temperature within EACH set
# (BEOL/auxiliary-rail name parts stay separate). Under explicit nearest,
# only fixed-path cells on SCALING_POWER_NET are relinked and analyzed at
# that DB's nominal voltage.
# A numeric value retains the old policy: verify the restored DB, never relink.
set FIXED_LIBRARY_SET     ""
set FIXED_LIBRARY_VOLTAGE "restore" ;# keep restored DB; optional numeric nominal-V check
# ===================== END USER SETTINGS ======================

namespace eval auto_scaling {
    variable last_library_scope {}
    variable progress_file ""
    variable progress_monitor_pids {}
    variable progress_total_epoch 0
    variable progress_total_ms 0
    variable progress_current_phase STARTING
    variable progress_phase_epoch 0
}
proc auto_scaling::need {cfg key} {
    if {![dict exists $cfg $key] || [dict get $cfg $key] eq ""} {
        error "Missing setting: $key"
    }
    return [dict get $cfg $key]
}
proc auto_scaling::option {cfg key fallback} {
    if {[dict exists $cfg $key]} { return [dict get $cfg $key] }
    return $fallback
}
proc auto_scaling::number {value} {
    set value [string map {p . m -} [string tolower $value]]
    if {![string is double -strict $value] || ![expr {abs(double($value)) < 1e100}]} {
        error "Invalid finite number: $value"
    }
    return [expr {double($value)}]
}
proc auto_scaling::same {a b} { return [expr {abs($a-$b) < 1e-8}] }
proc auto_scaling::readable {path} {
    if {![file isfile $path] || ![file readable $path]} { error "Cannot read file: $path" }
    return [file normalize $path]
}

proc auto_scaling::progress_write {phase phase_epoch} {
    variable progress_file
    variable progress_total_epoch
    if {$progress_file eq ""} { return }
    set tmp ${progress_file}.tmp
    set fp [open $tmp w]
    puts $fp "$phase $phase_epoch $progress_total_epoch"
    close $fp
    file rename -force $tmp $progress_file
}

proc auto_scaling::phase_start {label} {
    variable progress_total_ms
    variable progress_current_phase
    variable progress_phase_epoch
    set now_epoch [clock seconds]
    set now_ms [clock milliseconds]
    set progress_current_phase $label
    set progress_phase_epoch $now_epoch
    progress_write $label $now_epoch
    set total_min [expr {($now_ms - $progress_total_ms) / 60000.0}]
    puts [format "PHASE START: %-28s | section=0.0 min | total=%.2f min | time=%s" \
        $label $total_min [clock format $now_epoch -format {%Y-%m-%d %H:%M:%S}]]
    flush stdout
    return $now_ms
}

proc auto_scaling::phase_done {label phase_started_ms} {
    variable progress_total_ms
    set now_ms [clock milliseconds]
    set section_min [expr {($now_ms - $phase_started_ms) / 60000.0}]
    set total_min [expr {($now_ms - $progress_total_ms) / 60000.0}]
    puts [format "PHASE DONE : %-28s | section=%.2f min | total=%.2f min" \
        $label $section_min $total_min]
    flush stdout
}

proc auto_scaling::start_progress_monitor {interval_minutes} {
    variable progress_file
    variable progress_monitor_pids
    variable progress_total_epoch
    variable progress_total_ms
    variable progress_current_phase
    variable progress_phase_epoch

    if {![string is integer -strict $interval_minutes] || $interval_minutes <= 0} {
        error "PROGRESS_INTERVAL_MINUTES must be a positive integer."
    }
    set progress_total_epoch [clock seconds]
    set progress_total_ms [clock milliseconds]
    set progress_current_phase STARTING
    set progress_phase_epoch $progress_total_epoch
    set progress_file [file join /tmp auto_scaling_progress_[pid].status]
    progress_write STARTING $progress_total_epoch

    set interval_seconds [expr {$interval_minutes * 60}]
    set monitor_script {
status_file=$1
pt_pid=$2
interval=$3
while kill -0 "$pt_pid" 2>/dev/null; do
    sleep "$interval"
    kill -0 "$pt_pid" 2>/dev/null || exit 0
    [ -r "$status_file" ] || continue
    IFS=' ' read phase phase_started total_started < "$status_file"
    now=$(date +%s)
    section_seconds=$((now - phase_started))
    total_seconds=$((now - total_started))
    pt_state=$(ps -p "$pt_pid" -o stat= 2>/dev/null | tr -d ' ')
    pt_cpu=$(ps -p "$pt_pid" -o %cpu= 2>/dev/null | tr -d ' ')
    [ -n "$pt_state" ] || pt_state=unknown
    [ -n "$pt_cpu" ] || pt_cpu=unknown
    printf 'PROGRESS: phase=%s | section=%d min | total=%d min | running=yes | PT_PID=%s | state=%s | cpu=%s%%\n' \
        "$phase" "$((section_seconds / 60))" "$((total_seconds / 60))" "$pt_pid" "$pt_state" "$pt_cpu"
done
}
    if {[catch {
        set progress_monitor_pids [exec /bin/sh -c $monitor_script auto_scaling_monitor \
            $progress_file [pid] $interval_seconds >@stdout 2>/dev/null &]
    } reason]} {
        set progress_monitor_pids {}
        puts "WARNING: Could not start the progress monitor: $reason"
    }
    puts "RUN START: PT_PID=[pid] | progress_interval=$interval_minutes min"
    puts "PROGRESS MONITOR: current phase, phase elapsed time, and total elapsed time every $interval_minutes minute(s)."
    flush stdout
}

proc auto_scaling::stop_progress_monitor {{status SUCCESS}} {
    variable progress_file
    variable progress_monitor_pids
    variable progress_total_ms
    variable progress_current_phase
    variable progress_phase_epoch
    foreach monitor_pid $progress_monitor_pids {
        if {![catch {exec ps -o pid= --ppid $monitor_pid} child_text]} {
            foreach child_pid [split [string trim $child_text]] {
                if {$child_pid ne ""} { catch {exec kill $child_pid} }
            }
        }
        catch {exec kill $monitor_pid}
    }
    set now_ms [clock milliseconds]
    set now_epoch [clock seconds]
    set total_min [expr {($now_ms - $progress_total_ms) / 60000.0}]
    set section_min [expr {($now_epoch - $progress_phase_epoch) / 60.0}]
    puts [format "RUN END: status=%s | phase=%s | section=%.2f min | total=%.2f min" \
        $status $progress_current_phase $section_min $total_min]
    flush stdout
    if {$progress_file ne ""} { catch {file delete -force $progress_file} }
    set progress_monitor_pids {}
    set progress_file ""
}

# SPEF/GPD의 // CORNER_NAME은 PDK마다 RC_MAX, rcmax_model처럼 표기가
# 다를 수 있습니다. 세 가지 일반 이름은 자동 인식하고, 그 밖의 회사 고유
# 이름은 대소문자와 구분 기호를 제거한 정확한 이름으로 비교합니다.
proc auto_scaling::canonical_beol {value} {
    set compact [string tolower $value]
    regsub -all {[^[:alnum:]]} $compact "" compact
    if {[string first "rcmax" $compact] >= 0} { return RCMAX }
    if {[string first "rcmin" $compact] >= 0} { return RCMIN }
    if {[string first "cmax"  $compact] >= 0} { return CMAX }
    return [string toupper $compact]
}

# restore session의 현재 parasitic이 요청한 BEOL과 목표 온도인지 확인합니다.
# PrimeTime은 SPEF/GPD의 // CORNER_NAME과 // OPERATING_TEMPERATURE를
# 각각 아래 design attribute에 보존합니다. 확인할 수 없거나 다르면 중단하여
# 다른 BEOL/온도의 parasitic으로 그럴듯한 결과가 생성되는 것을 막습니다.
proc auto_scaling::verify_restored_parasitics {cfg} {
    set requested_raw [need $cfg target_beol]
    set requested [canonical_beol $requested_raw]
    if {$requested eq ""} {
        error "TARGET_BEOL is empty or has no valid name characters: '$requested_raw'"
    }

    set design [current_design]
    if {[catch {set corner_name [get_attribute $design parasitics_corner_name]} reason] ||
        [string trim $corner_name] eq ""} {
        error "Cannot determine restored parasitic BEOL. SPEF/GPD CORNER_NAME is required. TARGET_BEOL=$requested"
    }
    set actual [canonical_beol $corner_name]
    if {$actual eq ""} {
        error "Restored parasitic CORNER_NAME is empty or invalid: '$corner_name'"
    }
    if {$actual ne $requested} {
        error "BEOL mismatch: TARGET_BEOL=$requested, restored parasitic=$corner_name ($actual). Activate the target BEOL scenario/session before running."
    }

    if {[catch {
        set parasitic_t [number [get_attribute $design parasitics_operating_temperature]]
    } reason]} {
        error "Cannot determine restored parasitic temperature. SPEF/GPD OPERATING_TEMPERATURE is required: $reason"
    }
    set target_t [number [need $cfg target_t]]
    if {![same $parasitic_t $target_t]} {
        error "Parasitic temperature mismatch: TARGET_TEMPERATURE=$target_t C, restored parasitic=$parasitic_t C. Activate the target temperature scenario/session before running."
    }

    puts "TARGET BEOL: $requested"
    puts "RESTORED PARASITIC: CORNER_NAME='$corner_name', TEMPERATURE=$parasitic_t C"
    return [dict create requested_beol $requested corner_name $corner_name \
        temperature $parasitic_t]
}

# Read the original union idx from the key, including cut/recovered path lists.
# Never substitute the position in the current list for a stored path identity.
proc auto_scaling::fixed_path_indices {paths} {
    set indices {}
    set seen [dict create]
    foreach item $paths {
        set key [lindex $item 0]
        if {![regexp {#([0-9]+)$} $key -> digits] ||
            [scan $digits %d idx] != 1 || $idx < 1} {
            error "FP-010: Original fixed-path idx is missing or invalid in key='$key'. Expected a key ending in #<positive idx>; paths will not be renumbered."
        }
        if {[dict exists $seen $idx]} {
            error "FP-011: Duplicate original fixed-path idx=$idx in keys '[dict get $seen $idx]' and '$key'."
        }
        dict set seen $idx $key
        lappend indices $idx
    }
    return $indices
}

proc auto_scaling::read_fixed {path expected_type} {
    set path [readable $path]
    set fh [open $path r]
    fconfigure $fh -encoding utf-8
    set block ""
    set dtype ""
    set collecting 0
    set complete 0
    while {[gets $fh line] >= 0} {
        if {!$collecting} {
            if {[regexp {^\s*set\s+DTYPE\s+"?(max|min)"?(?:\s*;.*)?\s*$} $line -> value]} {
                set dtype $value
            }
            if {![regexp {^\s*set\s+FIXED_PATHS\s+\{} $line]} { continue }
            set collecting 1
            set block $line
            if {[info complete $block]} { set complete 1; break }
        } else {
            append block "\n" $line
            # Generated files close the literal list on its own line. Avoid
            # rescanning the entire list for every path in a large union.
            if {[string trim $line] eq "\}" && [info complete $block]} {
                set complete 1
                break
            }
        }
    }
    close $fh
    if {!$complete || [catch {llength $block} words] || $words != 3 ||
        [lindex $block 0] ne "set" || [lindex $block 1] ne "FIXED_PATHS"} {
        error "Expected a literal set FIXED_PATHS block in $path (1_union.py output). No Tcl commands were executed."
    }
    if {$dtype ne "" && $dtype ne $expected_type} {
        error "Fixed-path mode mismatch: file DTYPE=$dtype, scaling delay_type=$expected_type. Use the matching setup/hold union."
    }
    set paths [lindex $block 2]
    if {![llength $paths]} { error "FIXED_PATHS is empty: $path" }
    set seen [dict create]
    foreach item $paths {
        if {[llength $item] ni {4 5}} { error "Invalid fixed-path row (expected 4 or 5 fields): $item" }
        lassign $item key from to through edges
        if {$key eq "" || $from eq "" || $to eq ""} { error "Empty fixed-path key/from/to" }
        if {[dict exists $seen $key]} { error "Duplicate fixed-path key: $key" }
        dict set seen $key 1
        foreach pin $through { if {$pin eq ""} { error "Empty through pin: $key" } }
        if {[llength $edges]} {
            if {[llength $edges] != [llength $through]+2} { error "Invalid edge count: $key" }
            foreach edge $edges { if {$edge ni {r f}} { error "Invalid edge '$edge': $key" } }
        }
    }
    fixed_path_indices $paths
    return [dict create file $path dtype $dtype count [llength $paths] paths $paths]
}

# 공정 이름은 TT/SS/FF로 강제 변환하지 않습니다. 예를 들어 SSPG는 SSPG로
# 유지해야 같은 공정의 전압/온도 library만 scaling에 사용됩니다.
proc auto_scaling::process_name {text} {
    set lower [string tolower $text]
    if {[regexp {(^|[^[:alnum:]])((tt|ss|ff)[[:alpha:]]*)} $lower token prefix process]} {
        return [string toupper $process]
    }
    return ""
}

# report_lib의 Operating Conditions 표에서 한 library의 실제 조건을 읽습니다.
# PrimeTime scaling용 PVT library는 한 파일에 operating condition이 하나여야
# 자동 선택이 명확합니다. 여러 개이면 잘못 고르지 않고 중단합니다.
proc auto_scaling::report_operating_condition {lib path} {
    # The default two report digits turn 0.685 into 0.69. Read sufficient
    # precision for matching without exposing float32 representation noise,
    # then restore the user's setting even when report_lib fails. This does
    # not change library/cell conditions.
    set saved_digits [get_app_var report_default_significant_digits]
    if {$saved_digits != 6} { set_app_var report_default_significant_digits 6 }
    set report_failed [catch {
        redirect -variable report_text { report_lib -nosplit $lib }
    } reason]
    if {$saved_digits != 6} { set_app_var report_default_significant_digits $saved_digits }
    if {$report_failed} {
        error "report_lib failed for $path: $reason"
    }

    set in_table 0
    set rows {}
    foreach line [split $report_text "\n"] {
        set line [string trim $line]
        if {$line eq "Operating Conditions:"} {
            set in_table 1
            continue
        }
        if {!$in_table} { continue }
        if {$line eq ""} {
            if {[llength $rows]} { break }
            continue
        }

        set fields [regexp -all -inline {\S+} $line]
        if {[llength $fields] < 4} { continue }
        if {[catch {set process_value [number [lindex $fields 1]]}]} { continue }
        if {[catch {set temperature  [number [lindex $fields 2]]}]} { continue }
        if {[catch {set voltage      [number [lindex $fields 3]]}]} { continue }
        lappend rows [dict create name [lindex $fields 0] \
            process_value $process_value v $voltage t $temperature]
    }

    if {![llength $rows]} {
        error "report_lib has no readable Operating Conditions row: $path"
    }
    if {[llength $rows] != 1} {
        error "report_lib has [llength $rows] Operating Conditions rows; automatic selection is ambiguous: $path"
    }
    return [lindex $rows 0]
}

# library 이름에 주 전압과 보조 rail 전압이 함께 들어갈 수 있습니다. 이름의
# 모든 전압을 지우면 보조 rail 전압이 다른 library들이 한 family로 합쳐지므로,
# report_lib Operating Conditions와 일치하는 token 위치만 family 후보로 만듭니다.
proc auto_scaling::replace_matching_pvt_tokens {text pattern target replacement} {
    set result ""
    set cursor 0
    foreach range [regexp -all -inline -indices $pattern $text] {
        lassign $range first last
        append result [string range $text $cursor [expr {$first-1}]]
        set token [string range $text $first $last]
        set numeric [string range $token 0 end-1]
        if {![catch {set value [number $numeric]}] && [same $value $target]} {
            append result $replacement
        } else {
            append result $token
        }
        set cursor [expr {$last+1}]
    }
    append result [string range $text $cursor end]
    return $result
}

proc auto_scaling::replace_one_token {text range replacement} {
    lassign $range first last
    return "[string range $text 0 [expr {$first-1}]]${replacement}[string range $text [expr {$last+1}] end]"
}

proc auto_scaling::matching_pvt_ranges {text pattern target} {
    set matches {}
    foreach range [regexp -all -inline -indices $pattern $text] {
        lassign $range first last
        set token [string range $text $first $last]
        set numeric [string range $token 0 end-1]
        if {![catch {set value [number $numeric]}] && [same $value $target]} {
            lappend matches $range
        }
    }
    return $matches
}

proc auto_scaling::report_family_info {lib path process voltage temperature} {
    set family [get_attribute $lib full_name]
    if {$family eq ""} { set family [file rootname [file tail $path]] }
    set family [string tolower $family]
    set family [string map [list [string tolower $process] PROCESS] $family]
    set voltage_pattern {[0-9]+(?:[p.][0-9]+)?v}
    set voltage_tokens [regexp -all -inline $voltage_pattern $family]
    set family [replace_matching_pvt_tokens $family \
        {(?:m|-)?[0-9]+(?:[p.][0-9]+)?c} $temperature TEMPERATURE]
    set candidates {}
    foreach range [matching_pvt_ranges $family $voltage_pattern $voltage] {
        set candidate [replace_one_token $family $range VOLTAGE]
        if {[lsearch -exact $candidates $candidate] < 0} { lappend candidates $candidate }
    }
    if {![llength $candidates]} {
        # 이름의 전압 표기가 Operating Conditions 값과 직접 대응하지 않는
        # 구형 naming은 기존 방식으로만 후보를 만들고 이후 exact-grid 검증에 맡깁니다.
        set fallback $family
        regsub -all $voltage_pattern $fallback {VOLTAGE} fallback
        lappend candidates $fallback
    }
    return [dict create candidates $candidates voltage_tokens $voltage_tokens]
}

# 먼저 기존 파일명 규칙을 사용하고, 파일명에서 P/V/T를 못 찾을 때에는
# restore session에 올라온 library의 report_lib Operating Conditions를 사용합니다.
# override value: {process voltage temperature family}
proc auto_scaling::corner {lib path overrides} {
    if {[dict exists $overrides $path]} {
        set fields [dict get $overrides $path]
        if {[llength $fields] != 4} { error "corner_map entry needs {process voltage temperature family}: $path" }
        lassign $fields process v t family
    } else {
        set stem [file rootname [file tail $path]]
        set pattern {((?:tt|ss|ff)[[:alpha:]]*|sf|fs)_?([0-9]+(?:[p.][0-9]+)?)v_?(m?[0-9]+(?:[p.][0-9]+)?|-[0-9]+(?:[p.][0-9]+)?)c}
        if {[regexp -nocase $pattern $stem token process v t]} {
            regsub -nocase $pattern $stem {PVT} family
            set family [string tolower $family]
        } else {
            set condition [report_operating_condition $lib $path]
            set process [process_name [dict get $condition name]]
            if {$process eq ""} { set process [process_name $stem] }
            if {$process eq ""} {
                # TT/SS/FF 계열이 아닌 실제 condition 이름도 그대로 사용할 수 있습니다.
                set process [string toupper [dict get $condition name]]
            }
            set v [dict get $condition v]
            set t [dict get $condition t]
            set family_info [report_family_info $lib $path $process \
                [dict get $condition v] [dict get $condition t]]
            set family [lindex [dict get $family_info candidates] 0]
        }
    }
    set lib_name [get_attribute $lib full_name]
    set result [dict create file $path process [string toupper $process] \
        v [number $v] t [number $t] family $family lib_name $lib_name]
    if {[info exists family_info]} {
        dict set result family_candidates [dict get $family_info candidates]
        dict set result voltage_tokens [dict get $family_info voltage_tokens]
    }
    return $result
}

# 두 전압 token이 같은 값이 되는 코너에서는 한 row만 보고 어느 위치가 PVT
# 축인지 알 수 없습니다. 전체 loaded grid에서 각 후보가 이어지는 V/T 점 수를
# 비교하여 결정하고, 여전히 동률이면 임의 선택 대신 그 library를 한 점 static
# family로 보존합니다.
proc auto_scaling::resolve_family_candidates {rows mode {native_group_names {}}} {
    set native_names [dict create]
    foreach name $native_group_names { dict set native_names $name 1 }
    set support [dict create]
    set multi_rail_rows 0
    foreach row $rows {
        if {[dict exists $row family_candidates]} {
            set candidates [dict get $row family_candidates]
        } else {
            set candidates [list [dict get $row family]]
        }
        if {[dict exists $row voltage_tokens] && \
            [llength [dict get $row voltage_tokens]] > 1} {
            incr multi_rail_rows
        }
        foreach candidate $candidates {
            set key [list [dict get $row process] $candidate]
            dict lappend support $key [list [dict get $row v] [dict get $row t]]
        }
    }

    set resolved {}
    set grid_resolved 0
    set static_ambiguous 0
    set native_ambiguous 0
    foreach row $rows {
        if {[dict exists $row family_candidates]} {
            set candidates [dict get $row family_candidates]
        } else {
            set candidates [list [dict get $row family]]
        }
        if {[llength $candidates] <= 1} {
            lappend resolved $row
            continue
        }
        set best_score -1
        set winners {}
        foreach candidate $candidates {
            set key [list [dict get $row process] $candidate]
            set vs {}
            set ts {}
            set points {}
            foreach point [dict get $support $key] {
                lassign $point pv pt
                lappend vs $pv
                lappend ts $pt
                lappend points "$pv,$pt"
            }
            set nv [llength [lsort -real -unique $vs]]
            set nt [llength [lsort -real -unique $ts]]
            set np [llength [lsort -unique $points]]
            switch -- $mode {
                V  { set score [expr {$nv * 100000 + $np}] }
                T  { set score [expr {$nt * 100000 + $np}] }
                VT { set score [expr {$np * 100000 + $nv * 100 + $nt}] }
                default { set score $np }
            }
            if {$score > $best_score} {
                set best_score $score
                set winners [list $candidate]
            } elseif {$score == $best_score} {
                lappend winners $candidate
            }
        }
        if {[llength $winners] == 1} {
            dict set row family [lindex $winners 0]
            incr grid_resolved
        } else {
            dict set row family "__MULTIRAIL_STATIC__/[string tolower [dict get $row lib_name]]"
            if {[dict exists $native_names [dict get $row lib_name]]} {
                dict set row family_resolution ambiguous_native_group
                incr native_ambiguous
                puts "MULTI-RAIL NAME AMBIGUOUS -> NATIVE GROUP: LIB=[dict get $row lib_name] (scalar filename family unused)"
            } else {
                dict set row family_resolution ambiguous_static
                incr static_ambiguous
                puts "MULTI-RAIL AMBIGUOUS -> STATIC: LIB=[dict get $row lib_name] voltage_tokens=[dict get $row voltage_tokens]"
            }
        }
        lappend resolved $row
    }
    if {$multi_rail_rows} {
        puts "MULTI-RAIL NAME ANALYSIS: rows=$multi_rail_rows grid_resolved=$grid_resolved native_group=$native_ambiguous ambiguous_static=$static_ambiguous"
    }
    return $resolved
}

# Match actual linked libraries by source DB AND internal name. Loaded
# alternatives with the same internal name must not add unrelated families.
proc auto_scaling::family_used_by_design {rows families} {
    return [family_used_by_cells $rows $families [get_cells -quiet -hierarchical *]]
}

# fixed path의 launch/capture/through pin이 실제로 참조하는 library 이름을 얻습니다.
# fixed-path-only 모드에서 실제 scaling할 library family를 얻습니다.
proc auto_scaling::family_used_by_fixed_paths {rows families fixed} {
    set cells [fixed_path_cells $fixed]
    return [family_used_by_cells $rows $families $cells]
}

proc auto_scaling::family_used_by_cells {rows families cells} {
    set used_names [dict create]
    set used_keys [dict create]
    if {[sizeof_collection $cells]} {
        set lib_cells [get_lib_cells -quiet -of_objects $cells]
        foreach_in_collection lib [get_libs -quiet -of_objects $lib_cells] {
            set name [get_attribute $lib full_name]
            set source [get_attribute $lib source_file_name]
            if {$source eq ""} {
                error "LS-001: An instantiated library has no source_file_name; cannot safely identify its set. LIB=$name"
            }
            set path [file normalize $source]
            dict set used_names $name 1
            dict set used_keys [list $path $name] 1
        }
    }
    set matched {}
    set allowed_families [dict create]
    foreach family $families { dict set allowed_families $family 1 }
    foreach row $rows {
        if {![dict exists $allowed_families [dict get $row family]] ||
            ![dict exists $used_names [dict get $row lib_name]]} { continue }
        set key [list [file normalize [dict get $row file]] [dict get $row lib_name]]
        if {[dict exists $used_keys $key]} { lappend matched [dict get $row family] }
    }
    set result [dict create family_matches [lsort -unique $matched] \
        used_library_names [lsort [dict keys $used_names]] \
        used_library_keys [dict keys $used_keys]]
    dict set result cell_names [get_object_name $cells]
    return $result
}

proc auto_scaling::bracket {values target axis} {
    set lower ""
    set upper ""
    foreach value [lsort -real -unique $values] {
        if {[same $value $target]} { continue }
        if {$value < $target} { set lower $value }
        if {$value > $target && $upper eq ""} { set upper $value }
    }
    if {$lower eq "" || $upper eq ""} {
        error "Cannot bracket target $axis=$target. Extrapolation is not enabled."
    }
    return [list $lower $upper]
}

# Use PrimeTime's actual multirail group for fixed-path macro cells. Library
# filenames/one-dimensional nominal voltages cannot identify the VDDPE axis.
proc auto_scaling::native_umem_scope {supply cfg} {
    set raw_patterns [string trim [option $cfg vddpe_name_patterns "*u_mem*"]]
    if {$raw_patterns eq ""} {
        return [dict create cell_names {} library_names {} groups {} name_patterns {}]
    }
    set patterns {}
    foreach item [split $raw_patterns ,] {
        set pattern [string trim $item]
        if {$pattern eq ""} {
            error "UM-020: VDDPE_SCALING_NAME_PATTERNS has an empty comma-separated pattern."
        }
        lappend patterns $pattern
    }
    set path_cells [dict get $supply path_cells]
    set lib_cells [get_attribute $path_cells lib_cell]
    if {[sizeof_collection $lib_cells] != [sizeof_collection $path_cells]} {
        error "UM-021: Cannot map every fixed-path cell to its linked library."
    }
    set names {}
    set linked_libraries [dict create]
    foreach name [get_object_name $path_cells] lib_cell [get_object_name $lib_cells] {
        set slash [string first / $lib_cell]
        if {$slash <= 0} { error "UM-021: Cannot read linked library from $lib_cell" }
        set library [string range $lib_cell 0 [expr {$slash-1}]]
        dict set linked_libraries $library 1
        foreach pattern $patterns {
            if {[string match -nocase $pattern $name] ||
                [string match -nocase $pattern $library]} {
                lappend names $name
                puts "VDDPE MACRO MATCH: cell=$name library=$library pattern=$pattern"
                break
            }
        }
    }
    if {![llength $names]} {
        if {[string trim [option $cfg target_vddpe ""]] ne ""} {
            set sample [lrange [lsort [dict keys $linked_libraries]] 0 19]
            error "UM-022: TARGET_VDDPE_VOLTAGE was set, but VDDPE_SCALING_NAME_PATTERNS matched no fixed-path cell or linked library. Patterns=$patterns; linked library sample=$sample. Use an actual linked library name, not the synthetic library-set/family name."
        }
        return [dict create cell_names {} library_names {} groups {} name_patterns $patterns]
    }
    set requested [string trim [option $cfg target_vddpe ""]]
    if {$requested eq ""} {
        error "UM-001: VDDPE_SCALING_NAME_PATTERNS selected fixed-path cells; set TARGET_VDDPE_VOLTAGE. It may differ from TARGET_VOLTAGE."
    }
    set target [number $requested]
    set target_t [number [need $cfg target_t]]
    set group_records {}
    set library_names [dict create]
    foreach name $names {
        set cell [get_cells -quiet -exact $name]
        if {[sizeof_collection $cell] != 1} { error "UM-002: Cannot resolve one u_mem cell: $name" }
        set pg [get_pg_pins -of_objects $cell]
        set found 0
        foreach_in_collection pin $pg {
            if {[string equal -nocase [get_attribute $pin pin_name] VDDPE] &&
                [get_attribute $pin type] eq "primary_power"} { set found 1; break }
        }
        if {!$found} { error "UM-003: u_mem cell has no primary_power VDDPE PG pin: $name" }
        set libs [get_libs -quiet -of_objects [get_lib_cells -quiet -of_objects $cell]]
        if {[sizeof_collection $libs] != 1} { error "UM-004: Cannot resolve one linked library for $name" }
        set lib_name [get_attribute $libs full_name]
        dict set library_names $lib_name 1
        if {[dict exists $group_records $lib_name]} { continue }
        set group [get_attribute -quiet $libs lib_scaling_group]
        if {$group eq "" || ![sizeof_collection $group]} {
            error "UM-005: $name uses $lib_name without an active native scaling group. No name-based group will be guessed."
        }
        redirect -variable report {
            report_lib_groups -scaling -objects $libs -nosplit -show {voltage temperature process}
        }
        set voltages {}
        set members [dict create]
        set matching_rail_vectors {}
        foreach line [split $report "\n"] {
            if {![regexp {^\s*(\S+)\s+(-?[0-9]+(?:\.[0-9]+)?)\s+\{([^\}]*)\}} $line -> member temp rails]} {
                continue
            }
            dict set members $member 1
            if {![same [number $temp] $target_t]} { continue }
            if {![regexp -nocase {(?:^|[[:space:]])VDDPE:([-+]?[0-9]+(?:\.[0-9]+)?)} $rails -> voltage]} {
                error "UM-006: Native group for $lib_name has no VDDPE rail at $target_t C. Check its Liberty rail name."
            }
            set parsed_voltage [number $voltage]
            lappend voltages $parsed_voltage
            if {[same $parsed_voltage $target]} {
                lappend matching_rail_vectors $rails
            }
        }
        if {![dict exists $members $lib_name]} {
            error "UM-007: Cannot locate linked library $lib_name in its native group report."
        }
        if {![llength $voltages]} {
            error "UM-008: No native VDDPE library grid at target temperature $target_t C for $lib_name."
        }
        if {[llength $matching_rail_vectors]} {
            error "UM-015: Native group for $lib_name contains VDDPE=$target V at $target_t C. A VDDPE match alone does not prove the full multirail target corner is present, so leave-one-out is unverified and this run stops. Matching rail vectors (first 5): [lrange $matching_rail_vectors 0 4]"
        }
        if {[catch {set pair [bracket $voltages $target VDDPE]} problem]} {
            error "UM-009: Native group for $lib_name cannot perform target-excluded VDDPE interpolation: $problem; loaded VDDPE values=[lsort -real -unique $voltages]"
        }
        dict set group_records $lib_name [dict create report $report bracket $pair \
            members [dict keys $members]]
        puts "U_MEM NATIVE SCALING: lib=$lib_name target_vddpe=$target V bracket=$pair V fixed_path_cells=[llength $names]"
    }
    return [dict create cell_names [lsort -unique $names] \
        library_names [dict keys $library_names] groups $group_records \
        target_vddpe $target name_patterns $patterns]
}

proc auto_scaling::umem_control_cells {native} {
    set targets [dict get $native cell_names]
    set controls {}
    foreach name $targets {
        set lib_cell [get_lib_cells -quiet -of_objects [get_cells -quiet -exact $name]]
        foreach_in_collection candidate [get_cells -quiet -of_objects $lib_cell] {
            set other [get_attribute $candidate full_name]
            if {[lsearch -exact $targets $other] < 0} {
                lappend controls $other
                break
            }
        }
    }
    return [lsort -unique $controls]
}

proc auto_scaling::umem_pin_voltages {report names} {
    set selected [dict create]
    foreach name $names { dict set selected $name 1 }
    set result [dict create]
    foreach line [split $report "\n"] {
        set fields [regexp -all -inline {\S+} $line]
        if {[llength $fields] < 4} { continue }
        set name [lindex $fields 0]
        if {![dict exists $selected $name]} { continue }
        set pin [lindex $fields 1]
        set type [lindex $fields 2]
        if {$type ni {primary_power primary_ground internal_power internal_ground}} { continue }
        set value [lindex $fields 3]
        if {[catch {number $value} voltage]} { continue }
        dict set result [list $name $pin] $voltage
    }
    return $result
}

proc auto_scaling::umem_supply_voltages {report} {
    set result [dict create]
    set net ""
    foreach line [split $report "\n"] {
        if {[regexp {^[[:space:]]*Supply Net[[:space:]]*:[[:space:]]*(\S+)} $line -> name]} {
            set net $name
            dict set result [list $net exists] 1
        } elseif {$net ne "" &&
            [regexp {^[[:space:]]*(Max-delay Voltage|Min-delay Voltage)[[:space:]]*:[[:space:]]*(\S+)} $line -> key value]} {
            dict set result [list $net $key] $value
        }
    }
    return $result
}

proc auto_scaling::umem_power_snapshot {native controls} {
    set names [lsort -unique [concat [dict get $native cell_names] $controls]]
    redirect -variable pins {
        report_power_pin_info [get_cells -quiet -exact $names]
    }
    redirect -variable nets { report_supply_net }
    return [dict create pins_report $pins nets_report $nets \
        pins [umem_pin_voltages $pins $names] nets [umem_supply_voltages $nets]]
}

proc auto_scaling::verify_umem_power {out native controls before after} {
    set target [dict get $native target_vddpe]
    set errors {}
    set prior [dict get $before pins]
    set final [dict get $after pins]
    foreach cell [dict get $native cell_names] {
        set key [list $cell VDDPE]
        if {![dict exists $final $key] || ![same [dict get $final $key] $target]} {
            lappend errors "UM-011: Target $cell/VDDPE did not report $target V after set_voltage"
        }
    }
    foreach cell $controls {
        set seen 0
        dict for {key value} $prior {
            if {[lindex $key 0] ne $cell} { continue }
            set seen 1
            if {![dict exists $final $key] || ![same [dict get $final $key] $value]} {
                lappend errors "UM-012: Control cell PG voltage changed: $key"
            }
        }
        if {!$seen} { lappend errors "UM-012: Control cell PG voltage was not parsed: $cell" }
    }
    if {![dict size [dict get $before nets]] ||
        [dict get $before nets] ne [dict get $after nets]} {
        lappend errors "UM-013: Supply-net voltage report changed or could not be parsed"
    }
    set status [expr {[llength $errors] ? "FAILED" : "PASSED"}]
    set evidence "U_MEM_POWER_VERIFICATION: $status\nTARGET_VDDPE: $target V\nTARGET_CELLS: [dict get $native cell_names]\nCONTROL_CELLS: $controls\n"
    if {![llength $controls]} { append evidence "CONTROL_STATUS: no same-lib-cell instance outside fixed paths; net check still active\n" }
    foreach error $errors { append evidence "$error\n" }
    append evidence "\nBEFORE PIN REPORT\n[dict get $before pins_report]\nAFTER PIN REPORT\n[dict get $after pins_report]\n"
    append evidence "\nBEFORE SUPPLY REPORT\n[dict get $before nets_report]\nAFTER SUPPLY REPORT\n[dict get $after nets_report]\n"
    dict for {lib record} [dict get $native groups] {
        append evidence "\nNATIVE GROUP FOR $lib; bracket=[dict get $record bracket]\n[dict get $record report]\n"
    }
    set path [detail_path $out .umem_power.txt]
    write_text $path $evidence
    if {[llength $errors]} { error "U_MEM power verification failed: $errors. Evidence: $path" }
    puts "U_MEM POWER VERIFICATION: PASSED | evidence=$path"
    return $path
}

# 이 library set이 요청 축에서 실제로 변하는지 확인합니다. 한 점뿐인
# macro/IO library는 restore 상태 그대로 사용하고 scaling group에서 제외합니다.
proc auto_scaling::family_scaling_mode {rows process family tv tt requested_mode} {
    set vs_at_t {}
    set ts_at_v {}
    foreach row $rows {
        if {[dict get $row process] ne $process ||
            [dict get $row family] ne $family} {
            continue
        }
        if {[same [dict get $row t] $tt]} { lappend vs_at_t [dict get $row v] }
        if {[same [dict get $row v] $tv]} { lappend ts_at_v [dict get $row t] }
    }
    set nv [llength [lsort -real -unique $vs_at_t]]
    set nt [llength [lsort -real -unique $ts_at_v]]
    switch -- $requested_mode {
        V  { if {$nv <= 1} { return STATIC }; return V }
        T  { if {$nt <= 1} { return STATIC }; return T }
        VT {
            if {$nv <= 1 && $nt <= 1} { return STATIC }
            if {$nv > 1 && $nt <= 1} { return V }
            if {$nv <= 1 && $nt > 1} { return T }
            return VT
        }
    }
    error "Unknown scaling mode: $requested_mode"
}

proc auto_scaling::plan_one_family {rows process family tv tt mode} {
    set pool {}
    set excluded {}
    foreach row $rows {
        if {[dict get $row process] ne $process ||
            [dict get $row family] ne $family} {
            continue
        }
        if {[same [dict get $row v] $tv] && [same [dict get $row t] $tt]} {
            lappend excluded $row
        } else {
            lappend pool $row
        }
    }

    set eligible {}
    set vs {}
    set ts {}
    foreach row $pool {
        set v [dict get $row v]
        set t [dict get $row t]
        if {$mode eq "V" && ![same $t $tt]} { continue }
        if {$mode eq "T" && ![same $v $tv]} { continue }
        lappend eligible $row
        lappend vs $v
        lappend ts $t
    }

    if {$mode eq "T"} {
        set vv [list $tv]
    } else {
        set vv [bracket $vs $tv voltage]
    }
    if {$mode eq "V"} {
        set tts [list $tt]
    } else {
        set tts [bracket $ts $tt temperature]
    }

    set selected {}
    foreach v $vv {
        foreach t $tts {
            set matches {}
            foreach row $eligible {
                if {[same [dict get $row v] $v] && [same [dict get $row t] $t]} {
                    lappend matches $row
                }
            }
            if {[llength $matches] != 1} {
                set detail ""
                foreach match $matches {
                    append detail "\n  MATCH: LIB=[dict get $match lib_name] DB=[dict get $match file]"
                }
                if {![llength $matches]} {
                    append detail "\n  No library matched this exact process/voltage/temperature point."
                }
                error "library set '$family' needs exactly one library at $process/$v V/$t C; found [llength $matches]. Missing corner, merged library families, or duplicate revisions.$detail"
            }
            lappend selected [lindex $matches 0]
        }
    }

    return [dict create family $family mode $mode selected $selected excluded $excluded]
}

# Select declared fixed sets without guessing the meaning of numeric tokens.
# Exact names take precedence; only * and ? are wildcard operators.
# Brackets and backslashes in library-set names stay literal.
proc auto_scaling::resolve_fixed_families {spec families {strict 1}} {
    set spec [string trim $spec]
    if {$spec eq ""} { return {} }
    foreach family $families {
        if {[string equal -nocase $spec $family]} { return [list $family] }
    }
    if {[catch {llength $spec}] || ![llength $spec]} {
        error "FIXED_LIBRARY_SET must be empty, an exact name, or names/patterns separated by spaces."
    }
    set selected {}
    foreach selector $spec {
        set matches {}
        foreach family $families {
            if {[string equal -nocase $selector $family]} { lappend matches $family }
        }
        if {![llength $matches] && [regexp {[*?]} $selector]} {
            set pattern [string map [list "\\" "\\\\" "\[" "\\\[" "\]" "\\\]"] $selector]
            foreach family $families {
                if {[string match -nocase $pattern $family]} { lappend matches $family }
            }
        }
        if {![llength $matches] && $strict} {
            error "FIXED_LIBRARY_SET selector '$selector' is not a selected fixed-path library set or matching pattern. Available: $families"
        }
        set selected [concat $selected $matches]
    }
    return [lsort -unique $selected]
}

# This is a nearest-DB approximation, not interpolation or extrapolation.
# Never combine BEOL/auxiliary-rail variants or temperatures to fill gaps.
proc auto_scaling::nearest_library_row {rows process family tv tt} {
    set best {}
    set distance Inf
    foreach row $rows {
        if {[dict get $row process] ne $process || [dict get $row family] ne $family ||
            ![same [dict get $row t] $tt]} { continue }
        set d [expr {abs([dict get $row v] - $tv)}]
        if {$d < $distance - 1e-8} {
            set best [list $row]
            set distance $d
        } elseif {abs($d - $distance) < 1e-8} {
            lappend best $row
        }
    }
    if {![llength $best]} {
        error "NL-001: No loaded DB at the requested process/temperature for nearest selection: set=$family process=$process temperature=$tt C"
    }
    # Equal distances: use the lower voltage, then reject duplicate revisions.
    set voltage [dict get [lindex $best 0] v]
    foreach row $best { if {[dict get $row v] < $voltage} { set voltage [dict get $row v] } }
    set selected {}
    foreach row $best { if {[same [dict get $row v] $voltage]} { lappend selected $row } }
    if {[llength $selected] != 1} {
        error "NL-001: Nearest DB is ambiguous: set=$family voltage=$voltage V temperature=$tt C found=[llength $selected]. Different revisions are not merged."
    }
    return [lindex $selected 0]
}

proc auto_scaling::plan {cfg} {
    variable last_library_scope
    set last_library_scope {}
    set process [string toupper [need $cfg target_process]]
    set tv [number [need $cfg target_v]]
    set tt [number [need $cfg target_t]]
    set beol [canonical_beol [need $cfg target_beol]]
    if {$beol eq ""} {
        error "TARGET_BEOL is empty or has no valid name characters."
    }
    set mode [string toupper [need $cfg mode]]
    if {[lsearch -exact [list V T VT] $mode] < 0} {
        error "SCALING_AXIS must be V, T, or VT"
    }

    set fixed [option $cfg resolved_fixed ""]
    if {$fixed eq "" && [option $cfg fixed_tcl ""] ne ""} {
        set fixed [read_fixed [dict get $cfg fixed_tcl] [option $cfg delay_type max]]
    }
    if {$fixed eq ""} {
        error "FP-000: FIXED_PATH_FILE is required for fixed-path-only scaling."
    }

    # Resolve supply connections before asking any library set to interpolate.
    # This lookup does not require an existing scaling group.
    if {[dict exists $cfg fixed_path_supply]} {
        set supply [dict get $cfg fixed_path_supply]
    } else {
        set supply [classify_fixed_path_supply $fixed $cfg]
    }
    dict set fixed cell_names [get_object_name [dict get $supply path_cells]]

    set cat [catalog $cfg]
    set rows [dict get $cat rows]
    set families {}
    foreach row $rows {
        if {[dict get $row process] eq $process} {
            lappend families [dict get $row family]
        }
    }
    set families [lsort -unique $families]
    if {![llength $families]} {
        error "No loaded PVT library set matches process $process"
    }

    # 전체 design은 진단에만 사용합니다. 실제 scaling family와 cell은 사용자가
    # 선택한 reg-to-reg FIXED_PATHS 안으로 제한합니다.
    set used_result [family_used_by_design $rows $families]
    set used_matches [dict get $used_result family_matches]
    set used_names [dict get $used_result used_library_names]
    if {![llength $used_matches]} {
        error "No PVT library set matches the instantiated design. PVT candidates: $families; design-used library names: $used_names"
    }

    set fixed_result [family_used_by_fixed_paths $rows $families $fixed]
    if {[dict exists $fixed_result cell_names]} {
        dict set fixed cell_names [dict get $fixed_result cell_names]
    }
    set fixed_matches [dict get $fixed_result family_matches]
    set fixed_names [dict get $fixed_result used_library_names]
    if {![llength $fixed_matches]} {
        error "Fixed paths do not resolve to a loaded PVT library set. fixed-path library names: $fixed_names; design-used sets: $used_matches"
    }

    set rail_result [family_used_by_cells $rows $families [dict get $supply target_cells]]
    set rail_matches [dict get $rail_result family_matches]
    set native_umem [option $cfg native_umem [dict create cell_names {} library_names {} groups {}]]
    set native_names [dict get $native_umem library_names]
    set native_families {}
    foreach row $rows {
        if {[lsearch -exact $native_names [dict get $row lib_name]] >= 0} {
            lappend native_families [dict get $row family]
        }
    }
    set native_families [lsort -unique $native_families]
    # Retain read-only provenance even when the next bracket check fails.
    # The query Tcl can explain scope without repeating any PG-pin scan.
    set scope_context [dict create]
    foreach key {target_process target_v target_t target_beol mode scaling_power_nets fixed_tcl} {
        if {[dict exists $cfg $key]} { dict set scope_context $key [dict get $cfg $key] }
    }
    set design_name ""
    if {[llength [info commands ::current_design]]} {
        set design_name [get_object_name [current_design]]
    }
    set last_library_scope [dict create context $scope_context design_name $design_name \
        rows $rows fixed_result $fixed_result rail_result $rail_result]
    set fixed_rail_sets {}
    foreach family $fixed_matches {
        if {[lsearch -exact $rail_matches $family] < 0 &&
            [lsearch -exact $native_families $family] < 0} { lappend fixed_rail_sets $family }
    }
    puts "FIXED-RAIL LIBRARY SETS (no interpolation check): $fixed_rail_sets"

    set requested_family [option $cfg family ""]
    if {$requested_family ne ""} {
        if {[lsearch -exact $families $requested_family] < 0} {
            error "Requested library set is not available: $requested_family; candidates: $families"
        }
        if {[lsearch -exact $fixed_matches $requested_family] < 0} {
            error "Requested library set is not used by the fixed paths: $requested_family; fixed-path sets: $fixed_matches"
        }
        if {[lsearch -exact $rail_matches $requested_family] < 0} {
            error "Requested library set has no fixed-path cell on SCALING_POWER_NET: $requested_family"
        }
        set chosen_families [list $requested_family]
        puts "EXPLICIT LIBRARY SET OVERRIDE: $chosen_families"
    } else {
        set chosen_families $rail_matches
        puts "AUTO-SELECTED [llength $chosen_families] LIBRARY SET(S) ON FIXED-PATH SCALING POWER NET: $chosen_families"
    }
    # Native multirail VDDPE groups are already active. Their single nominal
    # voltage/name is not a valid scalar family interpolation axis.
    set scalar_families {}
    foreach family $chosen_families {
        if {[lsearch -exact $native_families $family] >= 0} {
            puts "U_MEM NATIVE GROUP REPLACES SCALAR FAMILY: $family"
        } else { lappend scalar_families $family }
    }
    set chosen_families $scalar_families
    puts "FIXED-PATH SCALING SCOPE: design sets=[llength $used_matches], path sets=[llength $fixed_matches], target-rail sets=[llength $chosen_families]"

    # Operating condition/family를 해석하지 못한 library라도 design에서 실제
    # 사용 중이면 숨기지 않습니다. scaling 가능 여부를 증명하지 못했으므로
    # unclassified/ungrouped로 남고 rail 단계의 static cell 수에는 포함됩니다.
    set unclassified_used {}
    foreach ignored [dict get $cat ignored] {
        set ignored_name [dict get $ignored lib_name]
        if {[lsearch -exact $fixed_names $ignored_name] >= 0 &&
            [lsearch -exact $native_names $ignored_name] < 0} {
            lappend unclassified_used $ignored_name
        }
    }
    set unclassified_used [lsort -unique $unclassified_used]
    if {[llength $unclassified_used]} {
        puts "UNCLASSIFIED FIXED-PATH LIBRARIES (not scaled): $unclassified_used"
    }

    set groups {}
    set static_sets $fixed_rail_sets
    set selected {}
    set excluded {}
    set fixed_library_rows {}
    set nearest_library_rows {}
    set fixed_families [resolve_fixed_families [option $cfg fixed_library_set ""] $fixed_matches]
    foreach family $native_families {
        if {[lsearch -exact $fixed_families $family] >= 0} {
            error "UM-010: FIXED_LIBRARY_SET selects u_mem family $family, but u_mem native scaling was requested. Remove this fixed-set exception."
        }
    }
    if {[llength $fixed_families]} {
        # A declared fixed set can be on another rail; still validate every DB.
        foreach family $fixed_families {
            if {[lsearch -exact $chosen_families $family] < 0} {
                lappend chosen_families $family
            }
        }
        set fixed_voltage [string tolower [string trim [option $cfg fixed_library_voltage restore]]]
        set nearest [string equal -nocase $fixed_voltage nearest]
        if {$fixed_voltage ni {nearest restore}} { set fixed_voltage [number $fixed_voltage] }
        foreach row $rows {
            if {[lsearch -exact $fixed_families [dict get $row family]] >= 0} {
                lappend fixed_library_rows $row
            }
        }
        puts "FIXED LIBRARY SET SELECTION: count=[llength $fixed_families] names=$fixed_families db_policy=$fixed_voltage"
        if {$nearest} {
            foreach family $fixed_families {
                if {[lsearch -exact $rail_matches $family] < 0} {
                    puts "NEAREST DB SKIPPED: set=$family reason=fixed_rail_only restore_DB_unchanged"
                    continue
                }
                set row [nearest_library_row $rows $process $family $tv $tt]
                lappend nearest_library_rows $row
                puts "NEAREST DB SELECTED: set=$family target=$tv V selected=[dict get $row v] V temperature=$tt C LIB=[dict get $row lib_name] DB=[dict get $row file]"
            }
        }
    }
    foreach family $chosen_families {
        if {[lsearch -exact $fixed_families $family] >= 0} {
            set static_sets [lsort -unique [concat $static_sets [list $family]]]
            puts "EXPLICIT FIXED LIBRARY SET: $family | db_policy=$fixed_voltage | interpolation disabled"
            continue
        }
        set family_mode [family_scaling_mode $rows $process $family $tv $tt $mode]
        if {$family_mode eq "STATIC"} {
            lappend static_sets $family
            puts "STATIC LIBRARY SET (not scaled): $family"
            continue
        }
        if {[catch {
            set group [plan_one_family $rows $process $family $tv $tt $family_mode]
        } reason]} {
            error "Cannot build scaling inputs for required library set '$family': $reason"
        }
        lappend groups $group
        foreach row [dict get $group selected] { lappend selected $row }
        foreach row [dict get $group excluded] { lappend excluded $row }
    }
    if {![llength $groups] && ![llength [dict get $native_umem cell_names]]} {
        error "The instantiated design uses no library set with a usable interpolation grid. Static sets: $static_sets"
    }

    set scaling_library_rows {}
    foreach row $rows {
        foreach group $groups {
            if {[dict get $row process] eq $process &&
                [dict get $row family] eq [dict get $group family]} {
                lappend scaling_library_rows $row
                break
            }
        }
    }

    set result [dict create]
    dict set result process $process
    dict set result v $tv
    dict set result t $tt
    dict set result beol $beol
    dict set result mode $mode
    dict set result family $chosen_families
    dict set result groups $groups
    dict set result static_sets $static_sets
    dict set result fixed_rail_sets $fixed_rail_sets
    dict set result scaling_library_rows $scaling_library_rows
    dict set result fixed_library_rows $fixed_library_rows
    dict set result explicit_fixed_sets $fixed_families
    dict set result nearest_library_rows $nearest_library_rows
    dict set result fixed_library_policy [expr {[string equal -nocase [option $cfg fixed_library_voltage ""] nearest] ? "nearest" : "restore"}]
    dict set result selected $selected
    dict set result excluded $excluded
    dict set result catalog $rows
    dict set result shadows [dict get $cat shadows]
    dict set result unclassified_used $unclassified_used
    dict set result native_umem $native_umem
    if {$fixed ne ""} { dict set result fixed $fixed }

    puts "TARGET: $process  $tv V  $tt C  $beol; mode=$mode; families=[llength $chosen_families]"
    foreach group $groups {
        puts "SCALING LIBRARY SET: [dict get $group family] (mode=[dict get $group mode])"
        if {![llength [dict get $group excluded]]} {
            puts "  TARGET LIBRARY: absent"
        }
        foreach row [dict get $group excluded] {
            puts "  EXCLUDED TARGET: process=[dict get $row process] voltage=[dict get $row v] V temperature=[dict get $row t] C DB=[dict get $row file]"
        }
        foreach row [dict get $group selected] {
            puts "  SCALING INPUT: process=[dict get $row process] voltage=[dict get $row v] V temperature=[dict get $row t] C DB=[dict get $row file]"
        }
    }
    if {[dict exists $result fixed]} {
        puts "FIXED PATHS: [dict get $result fixed count] from [dict get $result fixed file]"
    }

    # 전체 DB 중 얼마를 실제로 스케일링에 썼는지 한 줄로 요약합니다.
    # 로드된 라이브러리 대부분을 안 쓰는 것은 정상입니다(목표 전압을 양쪽에서
    # 끼는 두 개만 필요). 봐야 할 숫자는 static 쪽입니다 -- 디자인이 쓰는
    # library set 인데 보간 격자가 없어 원본 그대로 남은 것이므로, 그 셀이
    # 타이밍에 기여하면 이 결과는 반쪽입니다.
    set n_input 0
    foreach group $groups {
        incr n_input [llength [dict get $group selected]]
    }
    puts "SCALING COVERAGE: sets [llength $groups] scaled / [llength $static_sets] static\
 / [llength $chosen_families] chosen of [llength $families] candidate(s)"
    puts "SCALING COVERAGE: inputs $n_input DB of [llength $rows] loaded PVT librar\
[expr {[llength $rows] == 1 ? "y" : "ies"}]"
    if {[llength $static_sets]} {
        puts "SCALING COVERAGE: static set(s) not interpolated: $static_sets"
    }
    puts "SCALING COVERAGE: unclassified fixed-path libraries kept unscaled: [llength $unclassified_used]"
    return $result
}

proc auto_scaling::check_status {label command} {
    set status [uplevel 1 $command]
    if {$status ne "1"} { error "$label failed (return=$status); do not use this run as a valid scaling result" }
}

# Run once per fresh PT session. This procedure returns after analysis and

# 파일 시스템을 검색하지 않고 restore_session에 실제로 올라온 library만 목록화합니다.
proc auto_scaling::catalog {cfg} {
    if {![llength [info commands ::get_libs]]} {
        error "Loaded-library catalog requires pt_shell after restore_session."
    }
    set rows {}
    set ignored {}
    set seen [dict create]
    set overrides [option $cfg corner_map {}]
    foreach_in_collection lib [get_libs -quiet *] {
        set path [get_attribute $lib source_file_name]
        if {$path eq "" || [dict exists $seen $path]} { continue }
        dict set seen $path 1
        set lib_name [get_attribute $lib full_name]
        if {[catch {set row [corner $lib $path $overrides]} reason]} {
            lappend ignored [dict create path $path lib_name $lib_name reason $reason]
            continue
        }
        lappend rows $row
    }
    set native_member_names {}
    set native_umem [option $cfg native_umem [dict create groups {}]]
    dict for {linked_lib group_record} [dict get $native_umem groups] {
        set native_member_names [concat $native_member_names [dict get $group_record members]]
    }
    set rows [resolve_family_candidates $rows [string toupper [option $cfg mode V]] \
        [lsort -unique $native_member_names]]
    if {![llength $rows]} {
        set detail ""
        foreach item [lrange $ignored 0 2] {
            append detail "\n  [dict get $item path]: [dict get $item reason]"
        }
        error "No loaded library P/V/T could be identified from filenames or report_lib.$detail"
    }
    puts "LOADED PVT LIBRARIES: [llength $rows]"
    if {[llength $ignored]} {
        puts "IGNORED NON-PVT LIBRARIES: [llength $ignored]"
    }
    return [dict create rows $rows shadows {} ignored $ignored]
}
proc auto_scaling::fixed_path_edge_opt {base_opt dir} {
  if {$dir eq "r"} {
    return "-rise_$base_opt"
  }
  if {$dir eq "f"} {
    return "-fall_$base_opt"
  }
  return "-$base_opt"
}

proc auto_scaling::report_fixed_paths {out_file paths delay_type pba_mode} {
    variable progress_total_ms
    set indices [fixed_path_indices $paths]
    set measured 0
    set missing {}
    set processed 0
    set total [llength $paths]
    set progress_started_ms [clock milliseconds]
    foreach item $paths idx $indices {
        incr processed
        if {$processed == 1 || $processed % 100 == 0 || $processed == $total} {
            set now_ms [clock milliseconds]
            set elapsed_min [expr {($now_ms - $progress_started_ms) / 60000.0}]
            set total_min [expr {($now_ms - $progress_total_ms) / 60000.0}]
            puts [format "FIXED PATH PROGRESS: %d/%d | section=%.2f min | total=%.2f min" \
                $processed $total $elapsed_min $total_min]
            flush stdout
        }
        lassign $item key from to through edges
        set pins [concat [list $from] $through [list $to]]
        set objects {}
        set bad_pin ""
        foreach pin $pins {
            set obj [get_pins -quiet $pin]
            if {[sizeof_collection $obj] != 1} { set bad_pin $pin; break }
            lappend objects $obj
        }
        set text ""
        set count 0
        if {$bad_pin ne ""} {
            set text "FIXED_PATH_STATUS: missing_or_ambiguous_pin $bad_pin"
        } else {
            set use_edges [expr {[llength $edges] == [llength $pins]}]
            set cmd [list report_timing -delay_type $delay_type -path_type full_clock_expanded \
                -max_paths 1 -sort_by slack -nets -input_pins -capacitance -transition_time \
                -nosplit -significant_digits 6]
            set i 0
            foreach obj $objects {
                if {$i == 0} { set base from } elseif {$i == [llength $objects]-1} {
                    set base to
                } else { set base through }
                set dir ""
                if {$use_edges} { set dir [lindex $edges $i] }
                lappend cmd [fixed_path_edge_opt $base $dir] $obj
                incr i
            }
            if {$pba_mode ne ""} { lappend cmd -pba_mode $pba_mode }
            if {[catch {redirect -variable text {eval $cmd}} problem]} {
                append text "\nFIXED_PATH_STATUS: report_error $problem"
            } else { set count [regexp -all -line {^\s*Startpoint:} $text] }
        }
        if {$count == 1} {
            incr measured
        } else {
            set status "no_timing_path"
            if {[regexp -line {^FIXED_PATH_STATUS:[[:space:]]*(.*)$} $text -> detail]} {
                set status $detail
            }
            lappend missing [dict create idx $idx key $key status $status]
        }
        redirect -append $out_file {
            puts "### FIXED_PATH idx=$idx key=$key"
            puts $text
            puts ""
        }
    }
    set missing_file [detail_path $out_file .missing]
    file mkdir [file dirname $missing_file]
    set fp [open $missing_file w]
    puts $fp "requested=$processed measured=$measured missing=[llength $missing]"
    foreach item $missing {
        puts $fp "idx=[dict get $item idx] key=[dict get $item key] status=[dict get $item status]"
    }
    close $fp

    puts "FIXED PATHS RESULT: requested=$processed measured=$measured missing=[llength $missing]"
    if {$measured == 0} {
        error "No fixed path was measured successfully. Inspect $out_file and $missing_file"
    }
    if {[llength $missing]} {
        puts "WARNING: [llength $missing] known/invalid fixed path(s) were skipped. Details: $missing_file"
    }
    return [dict create requested $processed measured $measured \
        missing [llength $missing] missing_file $missing_file]
}

# A capture D pin alone is not a cell delay arc. Require an actual input->output
# pair on the same scalable cell, rather than any scalable point on the path.
proc auto_scaling::scaling_cell_arc {timing_path scaled_names} {
    set previous ""
    foreach_in_collection point [get_attribute [index_collection $timing_path 0] points] {
        set pin [get_attribute $point object]
        if {$previous ne ""} {
            set a [get_cells -quiet -of_objects $previous]
            set b [get_cells -quiet -of_objects $pin]
            if {[sizeof_collection $a] == 1 && [sizeof_collection $b] == 1 &&
                [get_object_name $a] eq [get_object_name $b] &&
                [dict exists $scaled_names [get_object_name $a]] &&
                [get_attribute $previous direction] eq "in" &&
                [get_attribute $pin direction] eq "out"} {
                return [dict create from $previous to $pin cell [get_object_name $a]]
            }
        }
        set previous $pin
    }
    return {}
}

proc auto_scaling::find_scaling_fixed_path {fixed delay_type pba_mode scaled_cells} {
    set scaled_names [dict create]
    foreach name [get_object_name $scaled_cells] { dict set scaled_names $name 1 }
    set resolved 0
    foreach item [dict get $fixed paths] {
        lassign $item key from to through edges
        set pins [concat [list $from] $through [list $to]]
        set objects {}
        set valid 1
        foreach pin $pins {
            set obj [get_pins -quiet -exact $pin]
            if {[sizeof_collection $obj] != 1} { set valid 0; break }
            lappend objects $obj
        }
        if {!$valid} { continue }

        set use_edges [expr {[llength $edges] == [llength $pins]}]
        # get_timing_paths는 기본적으로 worst slack 순으로 반환합니다.
        # 일부 PrimeTime 버전에는 -sort_by 옵션이 없으므로 사용하지 않습니다.
        set cmd [list get_timing_paths -delay_type $delay_type -max_paths 1]
        set i 0
        foreach obj $objects {
            if {$i == 0} { set base from } elseif {$i == [llength $objects]-1} {
                set base to
            } else { set base through }
            set dir ""
            if {$use_edges} { set dir [lindex $edges $i] }
            lappend cmd [fixed_path_edge_opt $base $dir] $obj
            incr i
        }
        if {$pba_mode ne ""} { lappend cmd -pba_mode $pba_mode }
        if {[catch {set timing_path [eval $cmd]}] || ![sizeof_collection $timing_path]} {
            continue
        }
        incr resolved
        set arc [scaling_cell_arc $timing_path $scaled_names]
        if {$arc ne ""} {
            puts "SCALING EVIDENCE PATH: fixed_key=$key"
            puts "SCALING EVIDENCE ARC: cell=[dict get $arc cell] from=[get_object_name [dict get $arc from]] to=[get_object_name [dict get $arc to]]"
            return $timing_path
        }
    }
    if {$resolved} {
        error "SV-001: No input-to-output cell delay arc on a scaled cell in any resolved fixed path. resolved_paths=$resolved scaled_cells=[dict size $scaled_names]. A capture input pin alone is not a delay arc."
    }
    error "FP-009: No timing path resolved through the scalable fixed-path cells. Check path pins/edges, analysis type, and timing constraints."
}

# The diagnostic file is created before searching. Every verification failure
# records an ASCII status/code even when no delay calculation was possible.
proc auto_scaling::verify_scaling_result {out fixed delay_type pba_mode scaled_cells {suffix .dcalc}} {
    set evidence_file [detail_path $out $suffix]
    set header "SCALING_VERIFICATION_STATUS: STARTED\nANALYSIS_DELAY_TYPE: $delay_type\n"
    write_text $evidence_file $header
    set dcalc_text ""
    set code [catch {
        set timing_path [find_scaling_fixed_path $fixed $delay_type $pba_mode $scaled_cells]
        set scaled_names [dict create]
        foreach name [get_object_name $scaled_cells] { dict set scaled_names $name 1 }
        set arc [scaling_cell_arc $timing_path $scaled_names]
        if {$arc eq ""} { error "SV-001: The selected path no longer has a scalable cell delay arc." }
        set from_pin [dict get $arc from]
        set to_pin [dict get $arc to]
        set delay_option -$delay_type
        if {[catch {
            redirect -variable dcalc_text {
                report_delay_calculation $delay_option -from $from_pin -to $to_pin
            }
        } problem]} {
            error "SV-002: report_delay_calculation failed: $problem"
        }
        if {[regexp -nocase {SLG-320|DEL-012|scaling extrapolation problem|due to extrapolation in scaling} $dcalc_text]} {
            error "SV-003: Scaling extrapolation/cancellation detected. Evidence: $evidence_file"
        }
        if {[string first "Scaling libraries used" $dcalc_text] < 0} {
            error "SV-004: Scaling libraries used evidence is missing. Evidence: $evidence_file"
        }
    } result options]
    if {$code} {
        write_text $evidence_file "SCALING_VERIFICATION_STATUS: FAILED\nANALYSIS_DELAY_TYPE: $delay_type\nRUN ERROR: $result\n$dcalc_text"
        return -options $options $result
    }
    write_text $evidence_file "SCALING_VERIFICATION_STATUS: PASSED\nANALYSIS_DELAY_TYPE: $delay_type\nFROM_PIN: [get_object_name $from_pin]\nTO_PIN: [get_object_name $to_pin]\n$dcalc_text"
    puts "SCALING VERIFICATION: PASSED | evidence=$evidence_file"
    return $evidence_file
}

proc auto_scaling::report_has_corner {text rail voltage temperature} {
    foreach line [split $text "\n"] {
        if {![regexp {^\s+\S+\s+(-?[0-9]+(?:\.[0-9]+)?)\s+\{([^\n]*)\}} $line -> found_t rails]} {
            continue
        }
        # 실제 UPF supply 이름이 VDD가 아닐 수 있으므로 이 온도의 모든
        # power-rail voltage를 검사합니다. ground(보통 0V)는 일치하지 않습니다.
        foreach pair [regexp -all -inline {[^[:space:]:]+:[-+]?[0-9]+(?:\.[0-9]+)?} $rails] {
            set colon [string last ":" $pair]
            set found_v [string range $pair [expr {$colon+1}] end]
            if {[same [number $found_v] $voltage] &&
                [same [number $found_t] $temperature]} {
                return 1
            }
        }
    }
    return 0
}

# 기존 scaling group을 재사용하는 경우에도 fixed path용으로 계획한 각 입력
# DB가 실제 active group에 들어 있는지 확인합니다.
proc auto_scaling::verify_planned_group_coverage {plan} {
    set active_paths [dict create]
    foreach_in_collection lib [get_libs -quiet *] {
        set scaling_group [get_attribute -quiet $lib lib_scaling_group]
        if {$scaling_group eq "" || ![sizeof_collection $scaling_group]} { continue }
        set path [get_attribute -quiet $lib source_file_name]
        if {$path ne ""} { dict set active_paths [file normalize $path] 1 }
    }

    set planned 0
    set missing {}
    foreach group [dict get $plan groups] {
        foreach row [dict get $group selected] {
            incr planned
            set path [file normalize [dict get $row file]]
            if {![dict exists $active_paths $path]} { lappend missing $path }
        }
    }
    if {[llength $missing]} {
        error "Existing scaling groups do not cover every fixed-path scalable library family. Missing planned input DB(s): [lsort -unique $missing]"
    }
    puts "SCALING GROUP COVERAGE: all $planned planned input DB(s) are active"
}

# A fixed-set exception applies only to a whole group of that declared set.
# Mixed groups remain subject to the target-exclusion check.
proc auto_scaling::report_has_unapproved_corner {text plan rail voltage temperature} {
    if {![report_has_corner $text $rail $voltage $temperature]} { return 0 }
    set scoped [dict exists $plan scaling_library_rows]
    set relevant [dict create]
    foreach row [option $plan scaling_library_rows {}] {
        dict set relevant [list [file normalize [dict get $row file]] [dict get $row lib_name]] 1
    }
    set allowed [dict create]
    foreach row [option $plan fixed_library_rows {}] {
        dict set allowed [list [file normalize [dict get $row file]] [dict get $row lib_name]] 1
    }
    if {!$scoped && ![dict size $allowed]} { return 1 }
    set seen [dict create]
    foreach_in_collection lib [get_libs -quiet *] {
        set group [get_attribute -quiet $lib lib_scaling_group]
        if {$group eq "" || ![sizeof_collection $group]} { continue }
        set members [add_to_collection $group $lib]
        set keys {}
        set all_fixed 1
        set has_relevant 0
        foreach_in_collection member $members {
            set path [get_attribute $member source_file_name]
            set key [list [file normalize $path] [get_attribute $member full_name]]
            lappend keys $key
            if {![dict exists $allowed $key]} { set all_fixed 0 }
            if {[dict exists $relevant $key]} { set has_relevant 1 }
        }
        set keys [lsort -unique $keys]
        if {[dict exists $seen $keys]} { continue }
        dict set seen $keys 1
        # Groups unrelated to this run's target-rail families stay restored.
        # A mixed group touching a scaled family still gets the full check.
        if {$scoped && !$has_relevant} { continue }
        if {$all_fixed} { continue }
        redirect -variable group_text {
            report_lib_groups -scaling -objects $lib -nosplit -show {voltage temperature process}
        }
        if {[report_has_corner $group_text $rail $voltage $temperature]} { return 1 }
    }
    return 0
}

# Check the actual linked libraries BEFORE creating groups or applying V/T.
# Loaded alternative DBs are not evidence that the restored cells use them.
proc auto_scaling::validate_fixed_restore_libraries {fixed cfg} {
    set rows [option $cfg fixed_library_rows {}]
    if {![llength $rows]} { return [dict create names {} records {}] }
    set policy [dict create]
    foreach row $rows {
        dict set policy [list [file normalize [dict get $row file]] [dict get $row lib_name]] $row
    }
    set db_policy [string tolower [string trim [option $cfg fixed_library_voltage restore]]]
    set check_voltage [expr {$db_policy ni {nearest restore}}]
    if {$check_voltage} { set expected [number $db_policy] }
    set cells [fixed_path_cells $fixed]
    set libraries [get_libs -quiet -of_objects [get_lib_cells -quiet -of_objects $cells]]
    set decisions [dict create]
    set names {}
    set records {}
    foreach_in_collection lib $libraries {
        set name [get_attribute $lib full_name]
        set path [file normalize [get_attribute $lib source_file_name]]
        set key [list $path $name]
        set keep [dict exists $policy $key]
        if {[dict exists $decisions $name] && [dict get $decisions $name] != $keep} {
            error "Fixed/scaling libraries share the same internal name '$name'. Cannot safely classify fixed-path cells by name. DB=$path"
        }
        dict set decisions $name $keep
        if {!$keep} { continue }
        set condition [report_operating_condition $lib $path]
        set actual [dict get $condition v]
        if {$check_voltage && ![same $actual $expected]} {
            error "FIXED_LIBRARY_SET is linked to $actual V, expected $expected V: $path. No DB was switched; restore the intended DB before running."
        }
        lappend names $name
        set row [dict get $policy $key]
        dict set row v $actual
        dict set row t [dict get $condition t]
        lappend records $row
        puts "FIXED RESTORE DB VERIFIED: LIB=$name | nominal_voltage=$actual V | temperature=[dict get $condition t] C | DB=$path"
    }
    if {![llength $records]} {
        error "FIXED_LIBRARY_SET does not match any actual linked fixed-path library. No DB was switched."
    }
    return [dict create names [lsort -unique $names] records $records]
}

proc auto_scaling::pg_connection_signature {cells} {
    set signature {}
    foreach_in_collection pg [get_pg_pins -of_objects $cells] {
        set net [get_supply_nets -quiet -of_objects $pg]
        if {[sizeof_collection $net] == 1} {
            set supply [get_attribute $net full_name]
        } else { set supply [get_attribute $pg supply_connection] }
        lappend signature [list [get_attribute $pg full_name] [get_attribute $pg type] $supply]
    }
    return [lsort $signature]
}

proc auto_scaling::signal_pin_signature {lib_cell} {
    set signature {}
    foreach_in_collection pin [get_lib_pins -quiet -of_objects $lib_cell] {
        lappend signature [list [file tail [get_attribute $pin full_name]] [get_attribute $pin direction]]
    }
    return [lsort $signature]
}

# Read-only preflight for ALL replacements before the first size_cell. Group
# instances by old reference to avoid a library/PG lookup for every path pin.
proc auto_scaling::plan_nearest_bindings {fixed cfg plan} {
    set nearest_rows [option $plan nearest_library_rows {}]
    if {![llength $nearest_rows]} { return {} }
    set by_family [dict create]
    foreach row $nearest_rows { dict set by_family [dict get $row family] $row }
    set policy [dict create]
    foreach row [dict get $plan fixed_library_rows] {
        dict set policy [list [file normalize [dict get $row file]] [dict get $row lib_name]] $row
    }
    set cells [dict get [dict get $cfg fixed_path_supply] target_cells]
    set lib_cells [get_attribute $cells lib_cell]
    if {[sizeof_collection $lib_cells] != [sizeof_collection $cells]} {
        error "NL-002: Cannot resolve every nearest-selection instance's library cell."
    }
    set used [dict create]
    foreach_in_collection lib [get_libs -quiet -of_objects [get_lib_cells -quiet -of_objects $cells]] {
        set name [get_attribute $lib full_name]
        set path [file normalize [get_attribute $lib source_file_name]]
        if {[dict exists $used $name] && [dict get $used $name] ne $path} {
            error "NL-002: Target-rail instances use different DBs with the same internal library name '$name'; cannot safely group references."
        }
        dict set used $name $path
    }
    set groups [dict create]
    foreach name [get_object_name $cells] ref [get_object_name $lib_cells] {
        set slash [string first / $ref]
        set lib_name [string range $ref 0 [expr {$slash-1}]]
        if {![dict exists $used $lib_name]} { continue }
        set key [list [dict get $used $lib_name] $lib_name]
        if {![dict exists $policy $key]} { continue }
        set family [dict get [dict get $policy $key] family]
        if {![dict exists $by_family $family]} { continue }
        dict lappend groups [list $key $ref $family] $name
    }
    set bindings {}
    set seen_families [dict create]
    dict for {key names} $groups {
        lassign $key old_key old_ref family
        set row [dict get $by_family $family]
        set new_key [list [file normalize [dict get $row file]] [dict get $row lib_name]]
        set base [string range $old_ref [expr {[string first / $old_ref]+1}] end]
        set exact "[dict get $row file]:[dict get $row lib_name]/$base"
        set target [get_lib_cells -quiet -exact [list $exact]]
        if {[sizeof_collection $target] != 1} {
            error "NL-002: Nearest DB lacks a unique same-name cell: $exact count=[sizeof_collection $target]"
        }
        set instances [get_cells -quiet -exact $names]
        set old [get_lib_cells -quiet -of_objects [index_collection $instances 0]]
        if {[signal_pin_signature $old] ne [signal_pin_signature $target]} {
            error "NL-002: Nearest DB signal-pin names/directions differ: set=$family cell=$base. No cells relinked."
        }
        set target_lib [get_libs -quiet -of_objects $target]
        set actual [report_operating_condition $target_lib [dict get $row file]]
        if {![same [dict get $actual v] [dict get $row v]] || ![same [dict get $actual t] [dict get $row t]]} {
            error "NL-002: Nearest DB's actual V/T differs from its catalog values: $exact"
        }
        # A restored max->min mapping can silently use another voltage DB
        # during hold/early analysis. Keep the mapping, but require the same
        # selected nominal V/T; never rewrite a library-wide relationship.
        set min_file [get_attribute -quiet $target_lib min_source_file_name]
        dict set row min_file ""
        if {$min_file ne ""} {
            set min_file [file normalize $min_file]
            dict set row min_file $min_file
            set min_lib [get_libs -quiet -exact [list [get_attribute $target_lib min_extended_name]]]
            if {[sizeof_collection $min_lib] != 1} {
                error "NL-002: Nearest DB's mapped min library is not uniquely loaded: $min_file"
            }
            set min_condition [report_operating_condition $min_lib $min_file]
            if {![same [dict get $min_condition v] [dict get $row v]] ||
                ![same [dict get $min_condition t] [dict get $row t]]} {
                error "NL-002: Nearest DB has a min-library mapping at different V/T: selected=[dict get $row v] V/[dict get $row t] C min=[dict get $min_condition v] V/[dict get $min_condition t] C DB=$min_file. No cells relinked; library-wide min mappings were not changed."
            }
            puts "NEAREST MIN DB VERIFIED: set=$family nominal_voltage=[dict get $row v] V temperature=[dict get $row t] C DB=$min_file"
        }
        lappend bindings [dict create row $row cell_names $names old_cell $old target_cell $target \
            changed [expr {$old_key ne $new_key}] pg_before [pg_connection_signature $instances]]
        dict set seen_families $family 1
    }
    foreach row $nearest_rows {
        if {![dict exists $seen_families [dict get $row family]]} {
            error "NL-002: Selected nearest set has no actual target-rail fixed-path instances: [dict get $row family]"
        }
    }
    return $bindings
}

# Verify concrete DB identity for every bound instance, not just a name or
# a list of loaded candidates. Also used by the same-session evidence retry.
proc auto_scaling::verify_nearest_bindings {records} {
    foreach record $records {
        set row [dict get $record row]
        set names [dict get $record cell_names]
        set cells [get_cells -quiet -exact $names]
        if {[sizeof_collection $cells] != [llength $names]} {
            error "NL-004: Nearest-selected instances are missing or ambiguous."
        }
        set libs [get_libs -quiet -of_objects [get_lib_cells -quiet -of_objects $cells]]
        if {[sizeof_collection $libs] != 1 ||
            [get_attribute $libs full_name] ne [dict get $row lib_name] ||
            [file normalize [get_attribute $libs source_file_name]] ne [file normalize [dict get $row file]]} {
            error "NL-004: Instances are not linked to the selected nearest DB: set=[dict get $row family]"
        }
        if {[dict exists $row min_file]} {
            set actual_min [get_attribute -quiet $libs min_source_file_name]
            if {$actual_min ne ""} { set actual_min [file normalize $actual_min] }
            if {$actual_min ne [dict get $row min_file]} {
                error "NL-004: Nearest DB's min-library mapping changed after preflight: set=[dict get $row family]"
            }
        }
        puts "NEAREST DB BINDING VERIFIED: set=[dict get $row family] cells=[llength $names] nominal_voltage=[dict get $row v] V LIB=[dict get $row lib_name] DB=[dict get $row file]"
    }
}

proc auto_scaling::apply_nearest_bindings {bindings} {
    set saved_strict [get_app_var eco_strict_pin_name_equivalence]
    set_app_var eco_strict_pin_name_equivalence true
    set changed {}
    set records {}
    set code [catch {
        foreach binding $bindings {
            set names [dict get $binding cell_names]
            set cells [get_cells -quiet -exact $names]
            if {[dict get $binding changed]} {
                # size_cell checks functional/timing-arc equivalence natively.
                # Track before the call so partial failures are rolled back.
                lappend changed $binding
                check_status size_cell [list size_cell $cells [dict get $binding target_cell]]
            }
            set cells [get_cells -quiet -exact $names]
            if {[pg_connection_signature $cells] ne [dict get $binding pg_before]} {
                error "NL-003: PG-pin names/types or supply connections changed during nearest DB relinking."
            }
            lappend records [dict create row [dict get $binding row] cell_names $names \
                changed [dict get $binding changed]]
        }
        verify_nearest_bindings $records
    } result options]
    if {$code} {
        foreach binding [lreverse $changed] {
            foreach name [dict get $binding cell_names] {
                if {[catch {
                    set cell [get_cells -quiet -exact $name]
                    set current [get_lib_cells -quiet -of_objects $cell]
                    if {[compare_collections $current [dict get $binding old_cell]] != 0} {
                        check_status rollback_size_cell [list size_cell $cell [dict get $binding old_cell]]
                    }
                } rollback]} {
                    puts "NL-003 ROLLBACK FAILED: $rollback. Restore a fresh session before retrying."
                }
            }
        }
    }
    set_app_var eco_strict_pin_name_equivalence $saved_strict
    if {$code} { return -options $options $result }
    return $records
}

# Analyze the selected DB at its OWN nominal voltage, including hold (-min).
# Apply only the original target-rail PG pins; other supplies remain unchanged.
proc auto_scaling::apply_nearest_conditions {records supply} {
    foreach record $records {
        set row [dict get $record row]
        set names [dict get $record cell_names]
        set voltage [dict get $row v]
        check_status nearest_set_temperature [list set_temperature [dict get $row t] \
            -object_list [get_cells -quiet -exact $names]]
        set selected [dict create]
        foreach name $names { dict set selected $name 1 }
        foreach group [dict get $supply voltage_groups] {
            set count 0
            foreach name [dict get $group cell_names] {
                if {![dict exists $selected $name]} { continue }
                check_status nearest_set_voltage [list set_voltage $voltage -min $voltage \
                    -cell [get_cells -quiet -exact $name] -pg_pin_name [dict get $group pin_name]]
                incr count
            }
            if {$count} {
                puts "NEAREST DB VOLTAGE APPLIED: set=[dict get $row family] nominal_voltage=$voltage V min_voltage=$voltage V pg_pin=[dict get $group pin_name] cells=$count"
            }
        }
    }
}

proc auto_scaling::write_text {path contents} {
    file mkdir [file dirname $path]
    set fp [open $path w]
    puts -nonewline $fp $contents
    close $fp
}

# Timing reports stay in RESULT_FOLDER; all companion files live in details/.
proc auto_scaling::detail_path {out suffix} {
    return [file join [file dirname $out] details "[file tail $out]$suffix"]
}

# Existing failed runs may still have the old adjacent companion files.
proc auto_scaling::existing_detail_path {out suffix} {
    set path [detail_path $out $suffix]
    if {[file exists $path]} { return $path }
    if {[file exists ${out}${suffix}]} { return ${out}${suffix} }
    return $path
}

# Preserve existing contents when an old failed run is retried. Never choose
# silently between two versions of the same companion file.
proc auto_scaling::move_legacy_details {out} {
    set moves {}
    foreach suffix {.missing .selection.tcl .inputs.txt .libgroups.before .libgroups .dcalc .umem.dcalc .umem_power.txt .log} {
        set old ${out}${suffix}
        if {[catch {file type $old} type options]} {
            if {[lrange [dict get $options -errorcode] 0 1] eq {POSIX ENOENT}} { continue }
            return -options $options $type
        }
        if {$type ni {file link}} { error "Cannot move a non-file output detail: $old" }
        set new [detail_path $out $suffix]
        if {![catch {file type $new}]} {
            error "SV-005: Both old and details/ versions exist; cannot safely merge: $new"
        }
        lappend moves [list $old $new]
    }
    file mkdir [file dirname [detail_path $out .log]]
    foreach pair $moves { file rename -- {*}$pair }
    return [llength $moves]
}

# Clear only this run's exact output names; never clear the result directory.
# Remove old sidecars too, so a failed rerun cannot retain old success evidence.
proc auto_scaling::reset_output_files {out {include_log 0}} {
    set suffixes {"" .missing .selection.tcl .inputs.txt .libgroups.before .libgroups .dcalc .umem.dcalc .umem_power.txt}
    if {$include_log} { lappend suffixes .log }
    set previous {}
    foreach suffix $suffixes {
        if {$suffix eq ""} {
            set paths [list $out]
        } else {
            # Clear both formats on a normal overwrite, including stale legacy
            # evidence beside the report. Other corners/files are preserved.
            set paths [list [detail_path $out $suffix] ${out}${suffix}]
        }
        foreach path $paths {
            if {[catch {file type $path} type options]} {
                if {[lrange [dict get $options -errorcode] 0 1] eq {POSIX ENOENT}} { continue }
                return -options $options $type
            }
            if {$type ni {file link}} {
                error "Output path is not a file or symlink; refusing to remove it: $path"
            }
            lappend previous $path
        }
    }
    foreach path $previous { file delete -- $path }
    return [llength $previous]
}

proc auto_scaling::scaling_inputs_text {plan} {
    set lines {}
    lappend lines "PrimeTime scaling input plan"
    lappend lines [format "TARGET process=%s voltage=%s V temperature=%s C beol=%s axis=%s" \
        [dict get $plan process] [dict get $plan v] [dict get $plan t] \
        [dict get $plan beol] [dict get $plan mode]]
    lappend lines "NOTE BEOL is the restored parasitic corner; it is not interpolated."
    foreach group [dict get $plan groups] {
        lappend lines [format "FAMILY %s mode=%s" \
            [dict get $group family] [dict get $group mode]]
        set input_index 0
        foreach row [dict get $group selected] {
            incr input_index
            lappend lines [format "  INPUT %d process=%s voltage=%s V temperature=%s C lib=%s" \
                $input_index [dict get $row process] [dict get $row v] \
                [dict get $row t] [dict get $row lib_name]]
            lappend lines "    DB=[dict get $row file]"
        }
        if {![llength [dict get $group excluded]]} {
            lappend lines "  EXCLUDED_TARGET absent"
        } else {
            foreach row [dict get $group excluded] {
                lappend lines [format "  EXCLUDED_TARGET process=%s voltage=%s V temperature=%s C lib=%s" \
                    [dict get $row process] [dict get $row v] [dict get $row t] \
                    [dict get $row lib_name]]
                lappend lines "    DB=[dict get $row file]"
            }
        }
        lappend lines [format "  INTERPOLATION inputs=%d -> target=%s V/%s C" \
            [llength [dict get $group selected]] [dict get $plan v] [dict get $plan t]]
    }
    set native_umem [option $plan native_umem [dict create cell_names {} groups {}]]
    lappend lines "VDDPE_MACRO_NAME_PATTERNS=[option $native_umem name_patterns {}]"
    dict for {lib record} [dict get $native_umem groups] {
        lappend lines "U_MEM_NATIVE_GROUP lib=$lib target_vddpe=[dict get $native_umem target_vddpe] V bracket=[dict get $record bracket] V"
        lappend lines "  FIXED_PATH_CELLS=[dict get $native_umem cell_names]"
        lappend lines "  NATIVE_GROUP_MEMBERS=[dict get $record members]"
        lappend lines "  TARGET_EXCLUDED=yes; verify PG/supply and macro arc in .umem_power.txt/.umem.dcalc"
    }
    foreach family [dict get $plan static_sets] {
        lappend lines "STATIC_UNSCALED family=$family"
    }
    foreach family [option $plan fixed_rail_sets {}] {
        lappend lines "FIXED_RAIL_UNSCALED family=$family reason=no_fixed_path_cell_on_scaling_power_net"
    }
    foreach row [option $plan fixed_restore_records {}] {
        set label EXPLICIT_FIXED_RESTORE
        if {[option $plan fixed_library_policy restore] eq "nearest"} { set label FIXED_DB_USED }
        lappend lines "$label family=[dict get $row family] lib=[dict get $row lib_name] nominal_voltage=[dict get $row v] V temperature=[dict get $row t] C"
        lappend lines "  DB=[dict get $row file]"
    }
    foreach record [option $plan nearest_binding_records {}] {
        set row [dict get $record row]
        lappend lines "NEAREST_DB_BOUND family=[dict get $row family] target_voltage=[dict get $plan v] V selected_voltage=[dict get $row v] V temperature=[dict get $row t] C cells=[llength [dict get $record cell_names]] lib=[dict get $row lib_name]"
        lappend lines "  DB=[dict get $row file]"
        if {[option $row min_file ""] ne ""} { lappend lines "  MIN_DB=[dict get $row min_file]" }
    }
    foreach lib [dict get $plan unclassified_used] {
        lappend lines "UNCLASSIFIED_UNSCALED lib=$lib"
    }
    return "[join $lines \n]\n"
}

proc auto_scaling::fixed_path_cells {fixed} {
    if {[dict exists $fixed cell_names]} {
        set cached [get_cells -quiet -exact [dict get $fixed cell_names]]
        if {[sizeof_collection $cached] == [llength [dict get $fixed cell_names]]} {
            return $cached
        }
    }
    set cell_names {}
    foreach item [dict get $fixed paths] {
        lassign $item key from to through edges
        foreach pin [concat [list $from] $through [list $to]] {
            set slash [string last "/" $pin]
            if {$slash <= 0} {
                error "FP-001: Cannot extract an instance name from FIXED_PATHS pin: $pin"
            }
            lappend cell_names [string range $pin 0 [expr {$slash-1}]]
        }
    }
    set cell_names [lsort -unique $cell_names]
    set cells [get_cells -quiet -exact $cell_names]
    if {[sizeof_collection $cells] != [llength $cell_names]} {
        set missing {}
        foreach cell_name $cell_names {
            if {[sizeof_collection [get_cells -quiet -exact $cell_name]] != 1} {
                lappend missing $cell_name
            }
        }
        error "FP-002: FIXED_PATHS cells were not found uniquely in the current design: [lrange $missing 0 19]"
    }
    if {![sizeof_collection $cells]} {
        error "FP-003: No cells were found in FIXED_PATHS for the scaling scope."
    }
    return $cells
}

proc auto_scaling::resolve_configured_supply_roles {cfg} {
    set available [dict create]
    set supply_full_names {}
    foreach_in_collection supply [get_supply_nets -quiet -hierarchy *] {
        set full_name [get_attribute $supply full_name]
        lappend supply_full_names $full_name
        dict lappend available $full_name $full_name
        set object_name [get_object_name $supply]
        if {$object_name ne $full_name} { dict lappend available $object_name $full_name }
    }
    set supply_full_names [lsort -unique $supply_full_names]
    puts "RESTORED SUPPLY NETS: count=[llength $supply_full_names] names=$supply_full_names"
    if {![dict size $available]} {
        error "No supply nets were found in the restored session; cannot verify the scaling power net."
    }

    # 명시한 scaling net만 scaling으로 바꾸고 나머지는 모두 fixed로 둡니다.
    set roles [dict create]
    foreach full_name $supply_full_names { dict set roles $full_name fixed }
    set scaling_matches {}
    foreach requested [dict get $cfg scaling_power_nets] {
        if {![dict exists $available $requested]} {
            error "Configured scaling power net '$requested' was not found. Available supply nets: $supply_full_names"
        }
        set matches [lsort -unique [dict get $available $requested]]
        if {[llength $matches] != 1} {
            error "Configured scaling power net '$requested' matches multiple hierarchical nets: $matches. Use its full_name."
        }
        set actual [lindex $matches 0]
        if {[dict get $roles $actual] eq "scaling"} {
            error "Scaling power net '$actual' was configured twice."
        }
        dict set roles $actual scaling
        lappend scaling_matches $actual
        puts "CONFIGURED SCALING POWER NET MATCH: requested=$requested matched=$actual count=[llength $matches]"
    }
    set fixed_names {}
    dict for {name role} $roles {
        if {$role eq "fixed"} { lappend fixed_names $name }
    }
    set fixed_names [lsort $fixed_names]
    puts "SCALING POWER NETS: count=[llength $scaling_matches] names=[lsort $scaling_matches]"
    puts "AUTO-FIXED POWER NETS (unchanged): count=[llength $fixed_names] names=$fixed_names"
    return $roles
}

# Read-only supply classification, independent of library scaling groups.
# Run before interpolation planning so fixed rails cannot cause bracket errors.
proc auto_scaling::classify_fixed_path_supply {fixed cfg} {
    set path_cells [fixed_path_cells $fixed]
    if {[dict exists $cfg configured_supply_roles]} {
        set roles [dict get $cfg configured_supply_roles]
    } else {
        set roles [resolve_configured_supply_roles $cfg]
    }
    set pg_pins [get_pg_pins -of_objects $path_cells]
    set primary_pg [filter_collection $pg_pins {type == primary_power}]
    if {$primary_pg eq "" || ![sizeof_collection $primary_pg]} {
        error "FP-006: No type=primary_power PG pins were found on FIXED_PATHS cells. path_cells=[sizeof_collection $path_cells]"
    }

    set target_cell_names [dict create]
    set voltage_cells_by_pin [dict create]
    set voltage_rails_by_pin [dict create]
    set fixed_cell_names [dict create]
    set mapped_cell_names [dict create]
    set unknown_rails {}
    foreach_in_collection pg $primary_pg {
        # supply_connection 문자열은 hierarchical UPF에서 short name일 수 있으므로
        # 실제 supply object의 full_name을 기준으로 USER SETTINGS와 비교합니다.
        set connected_supply [get_supply_nets -quiet -of_objects $pg]
        if {[sizeof_collection $connected_supply] == 1} {
            set supply_name [get_attribute $connected_supply full_name]
        } else {
            set supply_name [get_attribute $pg supply_connection]
        }
        if {$supply_name eq "" || ![dict exists $roles $supply_name]} {
            lappend unknown_rails $supply_name
            continue
        }
        set pin_name [get_attribute $pg pin_name]
        set full_name [get_attribute $pg full_name]
        set suffix "/$pin_name"
        if {![string match "*$suffix" $full_name]} {
            error "Cannot extract a cell name from PG pin full_name: $full_name"
        }
        set cell_name [string range $full_name 0 end-[string length $suffix]]
        dict set mapped_cell_names $cell_name 1
        if {[dict get $roles $supply_name] eq "scaling"} {
            dict set target_cell_names $cell_name 1
            dict lappend voltage_cells_by_pin $pin_name $cell_name
            dict lappend voltage_rails_by_pin $pin_name $supply_name
        } else {
            dict set fixed_cell_names $cell_name 1
        }
    }
    set unknown_rails [lsort -unique $unknown_rails]
    if {[llength $unknown_rails]} {
        error "FP-007: FIXED_PATHS cells have primary supply rails absent from the restored supply-net map: $unknown_rails"
    }
    set unmapped_cells {}
    foreach cell_name [get_object_name $path_cells] {
        if {![dict exists $mapped_cell_names $cell_name]} { lappend unmapped_cells $cell_name }
    }
    if {[llength $unmapped_cells]} {
        error "FP-006: Cannot classify FIXED_PATHS cells without a connected primary_power PG pin: [lrange $unmapped_cells 0 19]"
    }
    if {![dict size $target_cell_names]} {
        error "FP-008: No FIXED_PATHS cell has a primary PG pin on SCALING_POWER_NET. path_cells=[sizeof_collection $path_cells] primary_pins=[sizeof_collection $primary_pg] fixed_rail_cells=[dict size $fixed_cell_names]"
    }

    set target_cells [get_cells -quiet -exact [dict keys $target_cell_names]]
    set voltage_groups {}
    foreach pin_name [lsort [dict keys $voltage_cells_by_pin]] {
        set cell_names [lsort -unique [dict get $voltage_cells_by_pin $pin_name]]
        set rails [lsort -unique [dict get $voltage_rails_by_pin $pin_name]]
        lappend voltage_groups [dict create pin_name $pin_name \
            cell_names $cell_names rails $rails]
    }
    set fixed_power_nets {}
    dict for {name role} $roles {
        if {$role eq "fixed"} { lappend fixed_power_nets $name }
    }
    set fixed_power_nets [lsort $fixed_power_nets]
    puts "FIXED-PATH SUPPLY SCOPE: all=[sizeof_collection $path_cells] target_rail=[sizeof_collection $target_cells] fixed_rail=[dict size $fixed_cell_names]"
    puts "AUTO-FIXED POWER NETS (unchanged): count=[llength $fixed_power_nets] names=$fixed_power_nets"
    puts "SCALING POWER NETS (fixed-path cell override only): [dict get $cfg scaling_power_nets]"

    return [dict create path_cells $path_cells target_cells $target_cells \
        voltage_groups $voltage_groups fixed_cell_names [dict keys $fixed_cell_names] \
        fixed_power_nets $fixed_power_nets]
}

# Filter the cached supply scope by the planned and active scaling libraries.
# Never query PG connections again during the same run.
proc auto_scaling::plan_fixed_path_power {fixed cfg} {
    if {[dict exists $cfg fixed_path_supply]} {
        set supply [dict get $cfg fixed_path_supply]
    } else {
        set supply [classify_fixed_path_supply $fixed $cfg]
    }
    set path_cells [dict get $supply path_cells]
    set path_lib_cells [get_attribute $path_cells lib_cell]
    if {[sizeof_collection $path_lib_cells] != [sizeof_collection $path_cells]} {
        error "FP-004: Cannot resolve lib_cell for every FIXED_PATHS cell. cells=[sizeof_collection $path_cells] lib_cells=[sizeof_collection $path_lib_cells]"
    }
    set used_libs [get_libs -quiet -of_objects [get_lib_cells -quiet -of_objects $path_cells]]
    set scalable_lib_names [dict create]
    set explicit_fixed_names [option $cfg fixed_library_names {}]
    foreach_in_collection lib $used_libs {
        set lib_name [get_attribute $lib full_name]
        if {[lsearch -exact $explicit_fixed_names $lib_name] >= 0} { continue }
        if {[dict exists $cfg scaling_library_names] &&
            [lsearch -exact [dict get $cfg scaling_library_names] $lib_name] < 0} { continue }
        set scaling_group [get_attribute -quiet $lib lib_scaling_group]
        if {$scaling_group ne "" && [sizeof_collection $scaling_group]} {
            dict set scalable_lib_names $lib_name 1
        }
    }
    set scalable_names [dict create]
    set static_count 0
    foreach cell_name [get_object_name $path_cells] lib_cell_name [get_object_name $path_lib_cells] {
        set slash [string first "/" $lib_cell_name]
        if {$slash <= 0} { error "Cannot extract a library name from lib_cell: $lib_cell_name" }
        set lib_name [string range $lib_cell_name 0 [expr {$slash-1}]]
        if {[dict exists $scalable_lib_names $lib_name]} {
            dict set scalable_names $cell_name 1
        } else {
            incr static_count
        }
    }
    if {![dict size $scalable_names]} {
        error "FP-005: No fixed-path cell uses an active scaling group after fixed-library exclusions. path_cells=[sizeof_collection $path_cells] explicit_fixed_libraries=[llength $explicit_fixed_names]"
    }
    set target_names [dict create]
    set voltage_groups {}
    foreach group [dict get $supply voltage_groups] {
        set names {}
        foreach cell_name [dict get $group cell_names] {
            if {![dict exists $scalable_names $cell_name]} { continue }
            lappend names $cell_name
            dict set target_names $cell_name 1
        }
        if {![llength $names]} { continue }
        dict set group cell_names $names
        lappend voltage_groups $group
        puts "FIXED-PATH VOLTAGE GROUP: pg_pin=[dict get $group pin_name] cells=[llength $names] rails=[dict get $group rails]"
    }
    set native_umem [option $cfg native_umem [dict create cell_names {}]]
    set native_cells [dict get $native_umem cell_names]
    foreach name $native_cells {
        if {![dict exists $scalable_names $name]} {
            error "UM-014: Fixed-path u_mem cell has no active native scaling library: $name"
        }
        dict set target_names $name 1
    }
    if {[llength $native_cells]} {
        lappend voltage_groups [dict create pin_name VDDPE cell_names $native_cells \
            rails VDDPE target_v [dict get $native_umem target_vddpe]]
        puts "FIXED-PATH U_MEM VOLTAGE GROUP: pg_pin=VDDPE cells=[llength $native_cells] target=[dict get $native_umem target_vddpe] V"
    }
    if {![dict size $target_names]} {
        error "FP-008: No scalable FIXED_PATHS cell has a primary PG pin on SCALING_POWER_NET. scalable_cells=[dict size $scalable_names]"
    }
    set target_cells [get_cells -quiet -exact [dict keys $target_names]]
    puts "FIXED-PATH CELL SCOPE: all=[sizeof_collection $path_cells] scalable_library=[dict size $scalable_names] target_voltage=[sizeof_collection $target_cells] static_library=$static_count"
    return [dict create path_cells $path_cells scaled_cells $target_cells \
        voltage_groups $voltage_groups fixed_cell_names [dict get $supply fixed_cell_names] \
        fixed_power_nets [dict get $supply fixed_power_nets]]
}

proc auto_scaling::run_after_restore {cfg} {
    variable last_library_scope
    set last_library_scope {}
    foreach command {
        get_designs get_libs get_lib_cells current_design define_scaling_lib_group
        report_lib_groups get_supply_nets get_pg_pins get_cells filter_collection
        report_power_pin_info report_supply_net
        set_temperature set_voltage update_timing get_timing_paths
    } {
        if {![llength [info commands ::$command]]} {
            error "Source this file in pt_shell after restore_session."
        }
    }
    if {![sizeof_collection [get_designs -quiet *]]} {
        error "No restored design was found. Run restore_session <session_directory> first."
    }
    if {![sizeof_collection [get_libs -quiet *]]} {
        error "No restored libraries were found. Check restore_session."
    }

    # 시간이 오래 걸리는 library 계획 전에 supply net 조회/설정을 먼저 검증합니다.
    set restored_cfg $cfg
    set phase_started [phase_start VERIFY_POWER_NETS]
    dict set restored_cfg configured_supply_roles [resolve_configured_supply_roles $cfg]
    phase_done VERIFY_POWER_NETS $phase_started

    # 복원 세션의 SPEF를 그대로 사용하므로 파일 기반 SPEF 선택은 수행하지 않습니다.
    # 대신 SPEF/GPD 헤더에서 복원된 BEOL과 온도를 읽어 목표와 정확히
    # 일치하는지 확인합니다. V/T/VT는 Liberty scaling 축입니다.
    set phase_started [phase_start VERIFY_PARASITICS]
    if {[dict exists $restored_cfg spef_template]} { dict unset restored_cfg spef_template }
    if {[dict exists $restored_cfg spef]} { dict unset restored_cfg spef }
    set parasitics [verify_restored_parasitics $restored_cfg]
    phase_done VERIFY_PARASITICS $phase_started

    set phase_started [phase_start CLASSIFY_FIXED_PATH_SUPPLY]
    set fixed [read_fixed [need $cfg fixed_tcl] [option $cfg delay_type max]]
    set supply [classify_fixed_path_supply $fixed $restored_cfg]
    set native_umem [native_umem_scope $supply $restored_cfg]
    dict set fixed cell_names [get_object_name [dict get $supply path_cells]]
    dict set restored_cfg resolved_fixed $fixed
    dict set restored_cfg fixed_path_supply $supply
    dict set restored_cfg native_umem $native_umem
    phase_done CLASSIFY_FIXED_PATH_SUPPLY $phase_started

    set phase_started [phase_start PLAN_DESIGN_LIBRARIES]
    set plan [plan $restored_cfg]
    dict set plan restored_parasitics $parasitics
    set fixed [expr {[dict exists $plan fixed] ? [dict get $plan fixed] : ""}]
    dict set restored_cfg fixed_library_rows [dict get $plan fixed_library_rows]
    set fixed_restore [validate_fixed_restore_libraries $fixed $restored_cfg]
    set nearest_bindings [plan_nearest_bindings $fixed $restored_cfg $plan]
    dict set restored_cfg fixed_library_names [dict get $fixed_restore names]
    set scaling_library_names {}
    foreach row [dict get $plan scaling_library_rows] {
        lappend scaling_library_names [dict get $row lib_name]
    }
    set scaling_library_names [concat $scaling_library_names [dict get $native_umem library_names]]
    dict set restored_cfg scaling_library_names [lsort -unique $scaling_library_names]
    dict set plan fixed_restore_records [dict get $fixed_restore records]
    set dt [option $cfg delay_type max]
    if {$dt ni {max min}} { error "delay_type must be max or min" }

    set original_out [file normalize [dict get $cfg out_rpt]]
    set out [file join [file dirname $original_out] "restored_[file tail $original_out]"]
    reset_output_files $out
    file mkdir [file dirname $out]
    set inputs_text [scaling_inputs_text $plan]
    write_text [detail_path $out .inputs.txt] $inputs_text
    puts $inputs_text
    phase_done PLAN_DESIGN_LIBRARIES $phase_started

    set rail [lindex [dict get $cfg scaling_power_nets] 0]
    set target_v [dict get $plan v]
    set target_t [dict get $plan t]
    set scaling_sets {}
    set seen_scaling_db [dict create]
    foreach group [dict get $plan groups] {
        set dbs {}
        foreach row [dict get $group selected] {
            set db [dict get $row file]
            if {[dict exists $seen_scaling_db $db]} {
                error "The same DB was selected for multiple scaling library sets: $db"
            }
            dict set seen_scaling_db $db 1
            lappend dbs $db
        }
        lappend scaling_sets [dict create name [dict get $group family] dbs $dbs]
    }

    set phase_started [phase_start PREPARE_SCALING_GROUPS]
    redirect -variable groups_before {
        report_lib_groups -scaling -nosplit -show {voltage temperature process}
    }
    write_text [detail_path $out .libgroups.before] $groups_before

    # restore session에 scaling group이 이미 있으면 그대로 재사용합니다.
    # 단, 목표 코너가 들어 있으면 leave-one-out이 아니므로 중단합니다.
    set has_existing_group [regexp -line {^Group[[:space:]]+[0-9]+} $groups_before]
    if {$has_existing_group} {
        if {[report_has_unapproved_corner $groups_before $plan $rail $target_v $target_t]} {
            error "An existing non-exempt scaling group contains target $target_v V/$target_t C. Target-excluded scaling cannot run with this group."
        }
        puts "RESTORE MODE: Reusing existing scaling groups."
    } else {
        puts "RESTORE MODE: Creating [llength $scaling_sets] scaling groups with the target corner excluded."
        foreach scaling_set $scaling_sets {
            set set_name [dict get $scaling_set name]
            set dbs [dict get $scaling_set dbs]
            puts "DEFINE SCALING LIBRARY SET: $set_name"
            if {[catch {define_scaling_lib_group $dbs} problem]} {
                error "Scaling group creation failed ($set_name): $problem. Check that the DBs model the same cells/pins."
            }
        }
    }

    redirect -variable groups_after {
        report_lib_groups -scaling -nosplit -show {voltage temperature process}
    }
    write_text [detail_path $out .libgroups] $groups_after
    if {[report_has_unapproved_corner $groups_after $plan $rail $target_v $target_t]} {
        error "A non-exempt scaling group still contains the target corner. Scaling verification failed: [detail_path $out .libgroups]"
    }
    verify_planned_group_coverage $plan
    phase_done PREPARE_SCALING_GROUPS $phase_started

    if {[llength $nearest_bindings]} {
        set phase_started [phase_start APPLY_NEAREST_LIBRARY_DB]
        set nearest_records [apply_nearest_bindings $nearest_bindings]
        apply_nearest_conditions $nearest_records $supply
        dict set plan nearest_binding_records $nearest_records
        set fixed_restore [validate_fixed_restore_libraries $fixed $restored_cfg]
        dict set restored_cfg fixed_library_names [dict get $fixed_restore names]
        dict set plan fixed_restore_records [dict get $fixed_restore records]
        write_text [detail_path $out .inputs.txt] [scaling_inputs_text $plan]
        foreach record $nearest_records {
            set row [dict get $record row]
            puts "NEAREST_DB_BOUND family=[dict get $row family] target_voltage=$target_v V selected_voltage=[dict get $row v] V cells=[llength [dict get $record cell_names]] lib=[dict get $row lib_name] DB=[dict get $row file]"
        }
        phase_done APPLY_NEAREST_LIBRARY_DB $phase_started
    }

    set phase_started [phase_start CLASSIFY_FIXED_PATH_POWER]
    set power_plan [plan_fixed_path_power $fixed $restored_cfg]
    set scaled_cells [dict get $power_plan scaled_cells]
    set voltage_groups [dict get $power_plan voltage_groups]
    foreach voltage_group $voltage_groups {
        if {[dict get $voltage_group pin_name] ne "VDDPE" ||
            [dict exists $voltage_group target_v]} { continue }
        foreach name [dict get $voltage_group cell_names] {
            if {[lsearch -exact [dict get $native_umem cell_names] $name] >= 0 &&
                ![same $target_v [dict get $native_umem target_vddpe]]} {
                error "UM-016: $name/VDDPE is on SCALING_POWER_NET, but core target ($target_v V) and VDDPE target ([dict get $native_umem target_vddpe] V) differ."
            }
        }
    }
    phase_done CLASSIFY_FIXED_PATH_POWER $phase_started

    set phase_started [phase_start APPLY_TARGET_VOLTAGE_TEMP]
    set umem_controls {}
    set umem_before {}
    if {[llength [dict get $native_umem cell_names]]} {
        set umem_controls [umem_control_cells $native_umem]
        set umem_before [umem_power_snapshot $native_umem $umem_controls]
    }
    check_status set_temperature [list set_temperature $target_t -object_list $scaled_cells]
    foreach voltage_group $voltage_groups {
        set pin_name [dict get $voltage_group pin_name]
        set cell_names [dict get $voltage_group cell_names]
        set group_v [option $voltage_group target_v $target_v]
        puts "APPLY CELL-LEVEL VOLTAGE: target=$group_v pg_pin=$pin_name cells=[llength $cell_names] rails=[dict get $voltage_group rails]"
        # PrimeTime의 set_voltage -cell은 한 번에 정확히 한 cell만 받습니다.
        foreach cell_name $cell_names {
            set voltage_cell [get_cells -quiet -exact $cell_name]
            check_status "set_voltage($cell_name/$pin_name)" [list set_voltage $group_v \
                -cell $voltage_cell -pg_pin_name $pin_name]
        }
    }
    if {[llength [dict get $native_umem cell_names]]} {
        set umem_after [umem_power_snapshot $native_umem $umem_controls]
        verify_umem_power $out $native_umem $umem_controls $umem_before $umem_after
    }
    phase_done APPLY_TARGET_VOLTAGE_TEMP $phase_started

    # restore_session에는 기존 timing 상태가 들어 있으므로 변경된 V/T와
    # scaling group의 영향만 갱신합니다. -full은 fixed path와 무관한
    # macro/IO net까지 처음부터 다시 계산하여 RC fallback과 실행 시간을
    # 불필요하게 늘릴 수 있습니다.
    set phase_started [phase_start UPDATE_TIMING_SI_POCV]
    check_status update_timing {update_timing}
    phase_done UPDATE_TIMING_SI_POCV $phase_started

    set phase_started [phase_start GENERATE_TIMING_REPORT]
    set fp [open [detail_path $out .selection.tcl] w]
    puts $fp "# restore_session scaling selection record"
    set record $plan
    dict unset record fixed paths
    if {[dict exists $record fixed cell_names]} { dict unset record fixed cell_names }
    # Keep the literal selection on one line for verify_after_run's parser.
    # The full native group report is retained in .umem_power.txt instead.
    if {[dict exists $record native_umem groups]} {
        dict for {lib group_record} [dict get $record native_umem groups] {
            dict unset record native_umem groups $lib report
        }
    }
    dict set record restored_design [get_object_name [current_design]]
    dict set record scaling_scope fixed_path_cells_only
    dict set record fixed_power_nets [dict get $power_plan fixed_power_nets]
    dict set record scaling_power_nets [dict get $cfg scaling_power_nets]
    dict set record scaled_cell_count [sizeof_collection $scaled_cells]
    puts $fp [list set scaling_selection $record]
    close $fp

    set fp [open $out w]
    puts $fp "### SCALING TARGET process=[dict get $plan process] voltage=[dict get $plan v] temperature=[dict get $plan t] beol=[dict get $plan beol] axis=[dict get $plan mode]"
    puts $fp "### RESTORED PARASITIC corner_name=[dict get $parasitics corner_name] temperature=[dict get $parasitics temperature]"
    puts $fp ""
    close $fp

    set fixed_result [report_fixed_paths $out [dict get $fixed paths] \
        $dt [option $cfg pba_mode ""]]
    if {![file exists $out] || [file size $out] == 0} {
        error "Timing report was not created or is empty: $out"
    }
    phase_done GENERATE_TIMING_REPORT $phase_started

    set phase_started [phase_start VERIFY_SCALING_RESULT]
    verify_nearest_bindings [option $plan nearest_binding_records {}]
    set core_names {}
    foreach name [get_object_name $scaled_cells] {
        if {[lsearch -exact [dict get $native_umem cell_names] $name] < 0} { lappend core_names $name }
    }
    if {[llength $core_names]} {
        verify_scaling_result $out $fixed $dt [option $cfg pba_mode ""] \
            [get_cells -quiet -exact $core_names]
    }
    if {[llength [dict get $native_umem cell_names]]} {
        verify_scaling_result $out $fixed $dt [option $cfg pba_mode ""] \
            [get_cells -quiet -exact [dict get $native_umem cell_names]] .umem.dcalc
    }
    phase_done VERIFY_SCALING_RESULT $phase_started

    puts "DONE: restore-session scaling report = $out"
    puts "FIXED PATH SUMMARY: requested=[dict get $fixed_result requested] measured=[dict get $fixed_result measured] missing=[dict get $fixed_result missing]"
    if {[llength $core_names]} { puts "VERIFY: scaling library evidence = [detail_path $out .dcalc]" }
    if {[llength [dict get $native_umem cell_names]]} {
        puts "VERIFY: u_mem scaling evidence = [detail_path $out .umem.dcalc]"
        puts "VERIFY: u_mem PG/supply evidence = [detail_path $out .umem_power.txt]"
    }
    return $out
}

proc auto_scaling::run_after_restore_monitored {cfg} {
    start_progress_monitor [option $cfg progress_minutes 10]
    set code [catch {run_after_restore $cfg} result options]
    if {$code} {
        stop_progress_monitor FAILED
    } else {
        stop_progress_monitor SUCCESS
    }
    if {$code} { return -options $options $result }
    return $result
}

# Retry only the final evidence check in the SAME still-loaded session after a
# failure. The caller keeps the original scaling_config across a load-only source.
# Never recreate groups, apply V/T, regenerate reports, or explicitly update timing.
proc auto_scaling::verify_after_run {cfg} {
    set requested_out [file normalize [need $cfg out_rpt]]
    set out [file join [file dirname $requested_out] "restored_[file tail $requested_out]"]
    readable $out
    set selection_file [readable [existing_detail_path $out .selection.tcl]]
    set fp [open $selection_file r]
    fconfigure $fp -encoding utf-8
    set selection ""
    while {[gets $fp line] >= 0} {
        if {[regexp {^set\s+scaling_selection\s+} $line] &&
            ![catch {llength $line} size] && $size == 3} {
            set selection [lindex $line 2]
            break
        }
    }
    close $fp
    if {$selection eq "" || [catch {dict size $selection}]} {
        error "SV-005: Cannot read the literal saved scaling selection: $selection_file"
    }
    if {[get_object_name [current_design]] ne [dict get $selection restored_design]} {
        error "SV-005: Current design differs from the saved scaling run. Use the same still-loaded session."
    }
    foreach {record_key config_key} {v target_v t target_t} {
        if {![same [dict get $selection $record_key] [number [need $cfg $config_key]]]} {
            error "SV-005: Saved scaling target and original config differ: $config_key"
        }
    }
    foreach {record_key config_key} {process target_process mode mode} {
        if {![string equal -nocase [dict get $selection $record_key] [need $cfg $config_key]]} {
            error "SV-005: Saved scaling target and original config differ: $config_key"
        }
    }
    if {[dict get $selection beol] ne [canonical_beol [need $cfg target_beol]] ||
        [lsort [dict get $selection scaling_power_nets]] ne [lsort [need $cfg scaling_power_nets]]} {
        error "SV-005: Saved BEOL or scaling supply nets differ from the original config."
    }
    set native_umem [option $selection native_umem [dict create cell_names {} library_names {}]]
    if {[llength [dict get $native_umem cell_names]] &&
        ![same [dict get $native_umem target_vddpe] [number [need $cfg target_vddpe]]]} {
        error "SV-005: Saved u_mem VDDPE target and current config differ."
    }
    set dt [option $cfg delay_type max]
    set fixed [read_fixed [dict get $selection fixed file] $dt]
    move_legacy_details $out
    set log_file [detail_path $out .log]
    set code [catch {
        redirect -tee -append $log_file {
            puts "VERIFY ONLY START: same-session evidence retry | report=$out"
            puts "VERIFY ONLY: keeping groups, cell V/T, and timing reports unchanged."
            verify_restored_parasitics $cfg
            verify_planned_group_coverage $selection
            set verify_cfg $cfg
            dict set verify_cfg fixed_library_rows [option $selection fixed_library_rows {}]
            set retained [validate_fixed_restore_libraries $fixed $verify_cfg]
            verify_nearest_bindings [option $selection nearest_binding_records {}]
            dict set verify_cfg fixed_library_names [dict get $retained names]
            dict set verify_cfg native_umem $native_umem
            if {[dict exists $selection scaling_library_rows]} {
                set scaling_names {}
                foreach row [dict get $selection scaling_library_rows] {
                    lappend scaling_names [dict get $row lib_name]
                }
                set scaling_names [concat $scaling_names [dict get $native_umem library_names]]
                dict set verify_cfg scaling_library_names [lsort -unique $scaling_names]
            }
            set power [plan_fixed_path_power $fixed $verify_cfg]
            set core_names {}
            foreach name [get_object_name [dict get $power scaled_cells]] {
                if {[lsearch -exact [dict get $native_umem cell_names] $name] < 0} { lappend core_names $name }
            }
            if {[llength $core_names]} {
                verify_scaling_result $out $fixed $dt [option $cfg pba_mode ""] \
                    [get_cells -quiet -exact $core_names]
            }
            if {[llength [dict get $native_umem cell_names]]} {
                verify_scaling_result $out $fixed $dt [option $cfg pba_mode ""] \
                    [get_cells -quiet -exact [dict get $native_umem cell_names]] .umem.dcalc
            }
            puts "VERIFY ONLY END: status=SUCCESS | core=[detail_path $out .dcalc] u_mem=[detail_path $out .umem.dcalc]"
        }
    } result options]
    if {$code} {
        set fp [open $log_file a]
        puts $fp "VERIFY ONLY END: status=FAILED"
        puts $fp "RUN ERROR: $result"
        close $fp
        return -options $options $result
    }
    return [detail_path $out .dcalc]
}



proc auto_scaling::build_restore_config {} {
    foreach name {
        TARGET_PROCESS TARGET_VOLTAGE TARGET_TEMPERATURE TARGET_BEOL SCALING_AXIS
        ANALYSIS FIXED_PATH_FILE RESULT_FOLDER PROGRESS_INTERVAL_MINUTES
        SCALING_POWER_NET VDDPE_SCALING_NAME_PATTERNS TARGET_VDDPE_VOLTAGE
        FIXED_LIBRARY_SET FIXED_LIBRARY_VOLTAGE
    } {
        if {![info exists ::$name]} {
            error "USER SETTINGS is missing $name."
        }
    }

    set analysis [string tolower $::ANALYSIS]
    switch -- $analysis {
        setup { set delay_type max }
        hold  { set delay_type min }
        default { error "ANALYSIS must be setup or hold." }
    }

    set voltage [number $::TARGET_VOLTAGE]
    set temperature [number $::TARGET_TEMPERATURE]
    set axis [string toupper $::SCALING_AXIS]
    if {[lsearch -exact {V T VT} $axis] < 0} {
        error "SCALING_AXIS must be V, T, or VT."
    }
    set progress_minutes $::PROGRESS_INTERVAL_MINUTES
    if {![string is integer -strict $progress_minutes] || $progress_minutes <= 0} {
        error "PROGRESS_INTERVAL_MINUTES must be a positive integer."
    }
    set vtag [string map {. p - m} [format %.12g $voltage]]
    set ttag [string map {. p - m} [format %.12g $temperature]]
    set beol [canonical_beol $::TARGET_BEOL]
    if {$beol eq ""} {
        error "TARGET_BEOL is empty or has no valid name characters."
    }
    set process $::TARGET_PROCESS
    if {[string trim $process] eq ""} {
        error "TARGET_PROCESS is empty."
    }
    set filename "scaled_[string toupper $process]_${vtag}V_${ttag}C_${beol}_${axis}_${analysis}.rpt"

    foreach {setting_name setting_value} [list \
        SCALING_POWER_NET $::SCALING_POWER_NET] {
        if {[string trim $setting_value] eq ""} {
            error "Set $setting_name in USER SETTINGS at the top of this Tcl."
        }
    }
    set scaling_power_nets [list $::SCALING_POWER_NET]

    set fixed_family [string trim $::FIXED_LIBRARY_SET]
    set fixed_voltage ""
    if {$fixed_family ne ""} {
        set policy [string tolower [string trim $::FIXED_LIBRARY_VOLTAGE]]
        if {$policy in {restore nearest}} {
            set fixed_voltage $policy
        } else { set fixed_voltage [number $policy] }
    }

    return [dict create \
        target_process $process \
        target_v $voltage \
        target_t $temperature \
        target_beol $beol \
        mode $axis \
        delay_type $delay_type \
        fixed_tcl $::FIXED_PATH_FILE \
        scaling_power_nets $scaling_power_nets \
        vddpe_name_patterns [string trim $::VDDPE_SCALING_NAME_PATTERNS] \
        target_vddpe [string trim $::TARGET_VDDPE_VOLTAGE] \
        fixed_library_set $fixed_family \
        fixed_library_voltage $fixed_voltage \
        progress_minutes $progress_minutes \
        out_rpt [file join $::RESULT_FOLDER $filename]]
}

proc auto_scaling::run_config_with_log {scaling_config} {
    set requested_out [file normalize [dict get $scaling_config out_rpt]]
    set actual_out [file join [file dirname $requested_out] \
        "restored_[file tail $requested_out]"]
    set log_file [detail_path $actual_out .log]
    file mkdir [file dirname $log_file]
    set previous_count [reset_output_files $actual_out 1]
    set code [catch {
        redirect -tee -file $log_file {
            puts "OUTPUT MODE: overwrite | previous_files_removed=$previous_count"
            set scaling_result [run_after_restore_monitored $scaling_config]
            puts "RUN COMPLETE: Restored-session scaling and fixed-path reporting finished."
        }
    } result options]
    if {$code} {
        set fp [open $log_file a]
        puts $fp "RUN ERROR: $result"
        close $fp
        return -options $options $result
    }
    puts "RUN LOG: $log_file"
    return $scaling_result
}

if {![info exists ::auto_scaling_restored_load_only] || !$::auto_scaling_restored_load_only} {
    set scaling_config [auto_scaling::build_restore_config]
    set scaling_result [auto_scaling::run_config_with_log $scaling_config]
}
