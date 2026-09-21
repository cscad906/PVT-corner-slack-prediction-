# PrimeTime restore_session 직후 실행하는 독립형 scaling 스크립트
#
# 사용 순서:
#   pt_shell
#   restore_session /path/to/saved_session
#   source /home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/pt/run_scaling_after_restore.tcl
#
# 현재 restore session에 이미 로드된 design/library/SDC/SPEF만 사용합니다.
# 이 파일은 read_db/read_verilog/link_design/read_sdc/read_parasitics를 실행하지 않습니다.
# 현재 활성 parasitic의 BEOL/온도가 목표와 일치할 때만 scaling을 실행합니다.

# ======================= USER SETTINGS ========================

# 목표 코너와 보간 방향
# V : 같은 process/temperature의 양쪽 voltage DB로 내삽 (기본값)
# T : 같은 process/voltage의 양쪽 temperature DB로 내삽
# VT: process가 같은 네 개의 voltage/temperature DB로 2D 내삽
# BEOL은 내삽하지 않고 목표 온도의 restore parasitic을 그대로 사용합니다.
set TARGET_PROCESS      "SSPG"    ;# report_lib에 표시되는 실제 공정 이름(예: TT, SSPG)
set TARGET_VOLTAGE      0.75      ;# Volt
set TARGET_TEMPERATURE  25        ;# Celsius. 영하 40도는 -40
set TARGET_BEOL         "rcmax"   ;# rcmax/cmax/rcmin 또는 session의 실제 CORNER_NAME
set SCALING_AXIS        "V"       ;# V / T / VT

# 분석 종류
set ANALYSIS            "setup"   ;# setup / hold

# 1_union.py가 만든 fixed path 파일.
# ""(빈 문자열)로 두면 fixed path 없이 스케일링만 하고, 아래 개수만큼
# 일반 report_timing으로 뽑습니다. 새 디자인을 처음 시험할 때 쓰세요.
# 주의: 코너마다 자기 기준 worst 경로가 나오므로 코너 간 비교에는 못 씁니다.
#       비교할 데이터를 만들 때는 반드시 fixed path 파일을 주세요.
set FIXED_PATH_FILE "fixed_paths.tcl"

# FIXED_PATH_FILE이 "" 일 때만 쓰입니다. report_timing -max_paths 값.
set FREE_REPORT_PATHS 100

# 결과 폴더
set RESULT_FOLDER "auto_scaling_output"

# 실행 상태를 이 간격마다 터미널에 출력합니다. update_timing처럼 PrimeTime이
# Tcl을 오래 점유하는 구간에서도 별도 감시 프로세스가 상태를 알려줍니다.
set PROGRESS_INTERVAL_MINUTES 10

# UPF가 없는 단일 전원 세션에서 생성할 기본 이름입니다.
# UPF가 복원되어 있으면 이 이름으로 rail을 고르지 않고, 실제로 scaling
# group에 속한 cell의 PG 연결을 따라 target rail을 자동 선택합니다.
set POWER_NET  "VDD"
set GROUND_NET "VSS"

# ===================== END USER SETTINGS =====================
# 아래 구현부는 수정하지 않아도 됩니다.
namespace eval auto_scaling {
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
        error "PROGRESS_INTERVAL_MINUTES는 1 이상의 정수여야 합니다."
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
        puts "WARNING: 상태 감시 프로세스를 시작하지 못했습니다: $reason"
    }
    puts "RUN START: PT_PID=[pid] | progress_interval=$interval_minutes min"
    puts "PROGRESS MONITOR: ${interval_minutes}분마다 현재 단계, 단계 경과 시간, 전체 경과 시간을 출력합니다."
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
        error "TARGET_BEOL이 비어 있거나 이름으로 사용할 문자가 없습니다: '$requested_raw'"
    }

    set design [current_design]
    if {[catch {set corner_name [get_attribute $design parasitics_corner_name]} reason] ||
        [string trim $corner_name] eq ""} {
        error "복원된 parasitic의 BEOL을 확인할 수 없습니다. SPEF/GPD의 // CORNER_NAME이 필요합니다. TARGET_BEOL=$requested"
    }
    set actual [canonical_beol $corner_name]
    if {$actual eq ""} {
        error "복원된 parasitic CORNER_NAME이 비어 있거나 이름으로 사용할 문자가 없습니다: '$corner_name'"
    }
    if {$actual ne $requested} {
        error "BEOL 불일치: TARGET_BEOL=$requested, restore session parasitic=$corner_name ($actual). 목표 BEOL scenario/session을 활성화한 뒤 다시 실행하세요."
    }

    if {[catch {
        set parasitic_t [number [get_attribute $design parasitics_operating_temperature]]
    } reason]} {
        error "복원된 parasitic 온도를 확인할 수 없습니다. SPEF/GPD의 // OPERATING_TEMPERATURE가 필요합니다: $reason"
    }
    set target_t [number [need $cfg target_t]]
    if {![same $parasitic_t $target_t]} {
        error "Parasitic 온도 불일치: TARGET_TEMPERATURE=$target_t C, restore session parasitic=$parasitic_t C. 목표 온도 scenario/session을 활성화한 뒤 다시 실행하세요."
    }

    puts "TARGET BEOL: $requested"
    puts "RESTORED PARASITIC: CORNER_NAME='$corner_name', TEMPERATURE=$parasitic_t C"
    return [dict create requested_beol $requested corner_name $corner_name \
        temperature $parasitic_t]
}

# Exact target-temperature extraction only: never use a nearest-temperature SPEF.
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
    if {[catch {
        redirect -variable report_text { report_lib -nosplit $lib }
    } reason]} {
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
proc auto_scaling::resolve_family_candidates {rows mode} {
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
            dict set row family_resolution ambiguous_static
            incr static_ambiguous
            puts "MULTI-RAIL AMBIGUOUS -> STATIC: LIB=[dict get $row lib_name] voltage_tokens=[dict get $row voltage_tokens]"
        }
        lappend resolved $row
    }
    if {$multi_rail_rows} {
        puts "MULTI-RAIL NAME ANALYSIS: rows=$multi_rail_rows grid_resolved=$grid_resolved ambiguous_static=$static_ambiguous"
    }
    return $resolved
}

# restore session의 현재 design 인스턴스들이 실제로 참조하는 library 이름입니다.
# 단순히 메모리에 load만 된 PDK library는 여기에 포함되지 않습니다.
proc auto_scaling::used_library_names {} {
    set names [dict create]
    if {![llength [info commands ::get_cells]] ||
        ![llength [info commands ::get_lib_cells]]} {
        return $names
    }
    set cells [get_cells -quiet -hierarchical *]
    if {![sizeof_collection $cells]} { return $names }
    set lib_cells [get_lib_cells -quiet -of_objects $cells]
    foreach_in_collection lib_cell $lib_cells {
        set full_name [get_attribute $lib_cell full_name]
        set slash [string first "/" $full_name]
        if {$slash > 0} {
            dict set names [string range $full_name 0 [expr {$slash-1}]] 1
        }
    }
    return $names
}

proc auto_scaling::family_used_by_design {rows families} {
    set used_names [used_library_names]
    return [families_matching_library_names $rows $families $used_names]
}

proc auto_scaling::families_matching_library_names {rows families used_names} {
    set matched {}
    foreach family $families {
        set is_used 0
        foreach row $rows {
            if {[dict get $row family] ne $family} { continue }
            if {[dict exists $used_names [dict get $row lib_name]]} {
                set is_used 1
                break
            }
        }
        if {$is_used} { lappend matched $family }
    }
    return [dict create family_matches [lsort -unique $matched] \
        used_library_names [lsort [dict keys $used_names]]]
}

# fixed path의 launch/capture/through pin이 실제로 참조하는 library 이름을 얻습니다.
# 이 정보는 report 대상 path가 어떤 family를 쓰는지 검증/출력하는 용도입니다.
# SI/POCV scaling family 선택 자체는 전체 instantiated design을 기준으로 합니다.
proc auto_scaling::family_used_by_fixed_paths {rows families fixed} {
    set pin_names {}
    foreach item [dict get $fixed paths] {
        lassign $item key from to through edges
        lappend pin_names $from $to
        foreach pin $through { lappend pin_names $pin }
    }
    set pin_names [lsort -unique $pin_names]
    set used_names [dict create]
    if {[llength $pin_names]} {
        set pins [get_pins -quiet -exact $pin_names]
        if {[sizeof_collection $pins]} {
            set cells [get_cells -quiet -of_objects $pins]
            if {[sizeof_collection $cells]} {
                set lib_cells [get_lib_cells -quiet -of_objects $cells]
                foreach_in_collection lib_cell $lib_cells {
                    set full_name [get_attribute $lib_cell full_name]
                    set slash [string first "/" $full_name]
                    if {$slash > 0} {
                        dict set used_names \
                            [string range $full_name 0 [expr {$slash-1}]] 1
                    }
                }
            }
        }
    }
    return [families_matching_library_names $rows $families $used_names]
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

proc auto_scaling::plan {cfg} {
    set process [string toupper [need $cfg target_process]]
    set tv [number [need $cfg target_v]]
    set tt [number [need $cfg target_t]]
    set beol [canonical_beol [need $cfg target_beol]]
    if {$beol eq ""} {
        error "TARGET_BEOL이 비어 있거나 이름으로 사용할 문자가 없습니다."
    }
    set mode [string toupper [need $cfg mode]]
    if {[lsearch -exact [list V T VT] $mode] < 0} {
        error "SCALING_AXIS must be V, T, or VT"
    }

    set fixed ""
    if {[option $cfg fixed_tcl ""] ne ""} {
        set fixed [read_fixed [dict get $cfg fixed_tcl] [option $cfg delay_type max]]
    }

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

    # SI aggressor와 그 timing window는 fixed path 밖의 cell에도 의존합니다.
    # 따라서 fixed path는 report 선택에만 사용하고, 실제 design에 instantiated된
    # 모든 PVT family를 scaling/static 판정 대상으로 삼습니다. 메모리에 load만
    # 되고 design에서 사용하지 않는 PDK library는 포함하지 않습니다.
    set used_result [family_used_by_design $rows $families]
    set used_matches [dict get $used_result family_matches]
    set used_names [dict get $used_result used_library_names]
    if {![llength $used_matches]} {
        error "No PVT library set matches the instantiated design. PVT candidates: $families; design-used library names: $used_names"
    }

    set requested_family [option $cfg family ""]
    if {$requested_family ne ""} {
        if {[lsearch -exact $families $requested_family] < 0} {
            error "Requested library set is not available: $requested_family; candidates: $families"
        }
        if {[lsearch -exact $used_matches $requested_family] < 0} {
            error "Requested library set is not instantiated in the design: $requested_family; design-used sets: $used_matches"
        }
        set chosen_families [list $requested_family]
        puts "EXPLICIT LIBRARY SET OVERRIDE: $chosen_families"
    } else {
        set chosen_families $used_matches
        puts "AUTO-SELECTED [llength $chosen_families] LIBRARY SET(S) USED BY ENTIRE DESIGN: $chosen_families"
    }

    if {$fixed ne ""} {
        set fixed_result [family_used_by_fixed_paths $rows $families $fixed]
        set fixed_matches [dict get $fixed_result family_matches]
        set fixed_names [dict get $fixed_result used_library_names]
        if {![llength $fixed_matches]} {
            error "Fixed paths do not resolve to a loaded PVT library set. fixed-path library names: $fixed_names; design-used sets: $used_matches"
        }
        puts "FIXED-PATH LIBRARY SET(S) (report selection only): $fixed_matches"
    }

    # Operating condition/family를 해석하지 못한 library라도 design에서 실제
    # 사용 중이면 숨기지 않습니다. scaling 가능 여부를 증명하지 못했으므로
    # unclassified/ungrouped로 남고 rail 단계의 static cell 수에는 포함됩니다.
    set unclassified_used {}
    foreach ignored [dict get $cat ignored] {
        set ignored_name [dict get $ignored lib_name]
        if {[lsearch -exact $used_names $ignored_name] >= 0} {
            lappend unclassified_used $ignored_name
        }
    }
    set unclassified_used [lsort -unique $unclassified_used]
    if {[llength $unclassified_used]} {
        puts "UNCLASSIFIED INSTANTIATED LIBRARIES (not scaled): $unclassified_used"
    }

    set groups {}
    set static_sets {}
    set selected {}
    set excluded {}
    foreach family $chosen_families {
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
    if {![llength $groups]} {
        error "The instantiated design uses no library set with a usable interpolation grid. Static sets: $static_sets"
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
    dict set result selected $selected
    dict set result excluded $excluded
    dict set result catalog $rows
    dict set result shadows [dict get $cat shadows]
    dict set result unclassified_used $unclassified_used
    if {$fixed ne ""} { dict set result fixed $fixed }

    puts "TARGET: $process  $tv V  $tt C  $beol; mode=$mode; families=[llength $chosen_families]"
    foreach group $groups {
        puts "SCALING LIBRARY SET: [dict get $group family] (mode=[dict get $group mode])"
        if {![llength [dict get $group excluded]]} {
            puts "  TARGET LIBRARY: absent"
        }
        foreach row [dict get $group excluded] {
            puts "  EXCLUDED TARGET: [dict get $row file]"
        }
        foreach row [dict get $group selected] {
            puts "  SCALING INPUT: [dict get $row file]"
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
        puts "SCALING COVERAGE: static set(s) kept at their original corner: $static_sets"
    }
    puts "SCALING COVERAGE: unclassified instantiated libraries kept unscaled: [llength $unclassified_used]"
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
    set rows [resolve_family_candidates $rows [string toupper [option $cfg mode V]]]
    if {![llength $rows]} {
        set detail ""
        foreach item [lrange $ignored 0 2] {
            append detail "\n  [dict get $item path]: [dict get $item reason]"
        }
        error "Restore session의 파일명과 report_lib에서 P/V/T를 식별할 library를 찾지 못했습니다.$detail"
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

# fixed path 없이 그 코너의 worst 경로를 그대로 뽑습니다. 스케일링이 걸렸는지
# 눈으로 보려는 용도입니다. 뽑히는 경로가 코너마다 달라지므로 코너 간 비교
# (2c/5c/7_cut/모델)에는 쓸 수 없고, 그래서 ### FIXED_PATH 마커도 안 붙입니다.
proc auto_scaling::report_free_paths {out_file delay_type max_paths pba_mode} {
    if {![string is integer -strict $max_paths] || $max_paths < 1} {
        error "FREE_REPORT_PATHS must be a positive integer: $max_paths"
    }
    set cmd [list report_timing -delay_type $delay_type -path_type full_clock_expanded \
        -max_paths $max_paths -nworst 1 -sort_by slack -nets -input_pins \
        -capacitance -transition_time -nosplit -significant_digits 6]
    if {$pba_mode ne ""} { lappend cmd -pba_mode $pba_mode }
    set text ""
    if {[catch {redirect -variable text {eval $cmd}} problem]} {
        error "report_timing failed: $problem"
    }
    set count [regexp -all -line {^\s*Startpoint:} $text]
    if {$count == 0} {
        error "No timing path was reported. Check the restored constraints and ANALYSIS."
    }
    redirect -append $out_file {
        puts "### FREE REPORT max_paths=$max_paths delay_type=$delay_type"
        puts $text
        puts ""
    }
    puts "FREE REPORT RESULT: paths=$count (requested up to $max_paths)"
    return [dict create requested $max_paths measured $count missing 0]
}

proc auto_scaling::report_fixed_paths {out_file paths delay_type pba_mode} {
    variable progress_total_ms
    set measured 0
    set missing {}
    set idx 0
    set total [llength $paths]
    set progress_started_ms [clock milliseconds]
    foreach item $paths {
        incr idx
        if {$idx == 1 || $idx % 100 == 0 || $idx == $total} {
            set now_ms [clock milliseconds]
            set elapsed_min [expr {($now_ms - $progress_started_ms) / 60000.0}]
            set total_min [expr {($now_ms - $progress_total_ms) / 60000.0}]
            puts [format "FIXED PATH PROGRESS: %d/%d | section=%.2f min | total=%.2f min" \
                $idx $total $elapsed_min $total_min]
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
    set missing_file ${out_file}.missing
    set fp [open $missing_file w]
    puts $fp "requested=$idx measured=$measured missing=[llength $missing]"
    foreach item $missing {
        puts $fp "idx=[dict get $item idx] key=[dict get $item key] status=[dict get $item status]"
    }
    close $fp

    puts "FIXED PATHS RESULT: requested=$idx measured=$measured missing=[llength $missing]"
    if {$measured == 0} {
        error "No fixed path was measured successfully. Inspect $out_file and $missing_file"
    }
    if {[llength $missing]} {
        puts "WARNING: [llength $missing] known/invalid fixed path(s) were skipped. Details: $missing_file"
    }
    return [dict create requested $idx measured $measured \
        missing [llength $missing] missing_file $missing_file]
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

# 기존 scaling group을 재사용하는 경우에도 전체 design용으로 계획한 각 입력
# DB가 실제 active group에 들어 있는지 확인합니다. 일부 family만 묶인 restore
# group을 조용히 재사용하면 fixed path 밖 SI/POCV cell이 원래 corner에 남습니다.
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
        error "Existing scaling groups do not cover every instantiated scalable library family. Missing planned input DB(s): [lsort -unique $missing]"
    }
    puts "SCALING GROUP COVERAGE: all $planned planned input DB(s) are active"
}

proc auto_scaling::write_text {path contents} {
    set fp [open $path w]
    puts -nonewline $fp $contents
    close $fp
}

# 두 collection을 합칩니다. 빈 collection handle도 안전하게 처리합니다.
proc auto_scaling::collection_union {left right} {
    if {$right eq "" || ![sizeof_collection $right]} { return $left }
    if {$left eq "" || ![sizeof_collection $left]} { return $right }
    return [add_to_collection -unique $left $right]
}

# 실제 design cell이 참조하는 library가 scaling group에 속하는지 조사하고,
# 그 cell에 연결된 power supply net을 자동 분류합니다. library 이름이나 SRAM
# instance 이름을 사용자가 나열하지 않습니다.
#
# scaled-only rail : target voltage 적용
# static-only rail : restore session의 전압 유지
# mixed rail       : 현재 전압이 이미 target이면 허용. 다르면 같은 물리 rail에
#                    서로 다른 전압을 줄 수 없으므로 set_voltage 전에 중단
proc auto_scaling::classify_scaling_power {cells target_v} {
    set used_lib_cells [get_lib_cells -quiet -of_objects $cells]
    if {![sizeof_collection $used_lib_cells]} {
        error "Design cell이 참조하는 library cell을 찾지 못해 supply rail을 자동 분류할 수 없습니다."
    }
    set used_libs [get_libs -quiet -of_objects $used_lib_cells]
    if {![sizeof_collection $used_libs]} {
        error "Design cell이 참조하는 owning library를 찾지 못해 supply rail을 자동 분류할 수 없습니다."
    }

    set scaled_cells ""
    set static_cells ""
    set scaled_supply ""
    set static_supply ""
    set scaled_by_rail [dict create]
    set static_by_rail [dict create]
    set no_supply_scaled {}
    set scaled_count 0
    set static_count 0

    # lib_cell마다 get_cells/get_supply_nets를 호출하면 큰 설계에서 수천 번의
    # collection query가 발생합니다. scaling group은 owning library 단위로
    # 동일하므로, 실제 사용 library별로 모든 instance를 한꺼번에 처리합니다.
    set lib_index 0
    set lib_total [sizeof_collection $used_libs]
    foreach_in_collection lib $used_libs {
        incr lib_index
        set lib_name [get_object_name $lib]
        set source_name ""
        catch { set source_name [file tail [get_attribute $lib source_file_name]] }
        set lib_label $lib_name
        if {$source_name ne ""} { append lib_label "($source_name)" }

        set library_cells [get_lib_cells -quiet -of_objects $lib]
        set design_cells [get_cells -quiet -of_objects $library_cells]
        if {![sizeof_collection $design_cells]} { continue }

        if {$lib_index == 1 || $lib_index % 10 == 0 || $lib_index == $lib_total} {
            puts "POWER RAIL PROGRESS: library=$lib_index/$lib_total instances=[sizeof_collection $design_cells]"
            flush stdout
        }

        set scaling_group [get_attribute -quiet $lib lib_scaling_group]
        set is_scaled [expr {$scaling_group ne "" && [sizeof_collection $scaling_group]}]
        set supplies [get_supply_nets -quiet -pg_types power -of_objects $design_cells]

        if {$is_scaled} {
            incr scaled_count [sizeof_collection $design_cells]
            set scaled_cells [collection_union $scaled_cells $design_cells]
            set scaled_supply [collection_union $scaled_supply $supplies]
            if {![sizeof_collection $supplies]} { lappend no_supply_scaled $lib_label }
        } else {
            incr static_count [sizeof_collection $design_cells]
            set static_cells [collection_union $static_cells $design_cells]
            set static_supply [collection_union $static_supply $supplies]
        }

        foreach_in_collection supply $supplies {
            set supply_name [get_attribute $supply full_name]
            if {$is_scaled} {
                dict lappend scaled_by_rail $supply_name $lib_label
            } else {
                dict lappend static_by_rail $supply_name $lib_label
            }
        }
    }

    if {$scaled_cells eq "" || ![sizeof_collection $scaled_cells]} {
        error "Scaling group에 속한 instantiated cell이 없습니다. 기존/생성된 scaling group과 linked library를 확인하세요."
    }
    if {[llength $no_supply_scaled]} {
        error "Scaling 대상 library cell의 power supply net을 찾지 못했습니다: [lsort -unique $no_supply_scaled]"
    }
    if {$scaled_supply eq "" || ![sizeof_collection $scaled_supply]} {
        error "Scaling 대상 cell에 연결된 power supply net이 없습니다. UPF/PG 연결을 확인하세요."
    }

    set scaled_names [lsort [dict keys $scaled_by_rail]]
    set static_names [lsort [dict keys $static_by_rail]]
    set mixed_bad {}
    set mixed_ok {}
    set scaled_only {}
    set static_only {}

    foreach supply_name $scaled_names {
        if {![dict exists $static_by_rail $supply_name]} {
            lappend scaled_only $supply_name
            continue
        }

        set supply [get_supply_nets -quiet $supply_name]
        set vmin "unknown"
        set vmax "unknown"
        catch { set vmin [number [get_attribute $supply voltage_min]] }
        catch { set vmax [number [get_attribute $supply voltage_max]] }
        if {$vmin ne "unknown" && $vmax ne "unknown" &&
            [same $vmin $target_v] && [same $vmax $target_v]} {
            lappend mixed_ok $supply_name
        } else {
            lappend mixed_bad $supply_name
        }
        puts "SHARED POWER RAIL: $supply_name current_min=$vmin current_max=$vmax target=$target_v\
 scaled_libs=[lsort -unique [dict get $scaled_by_rail $supply_name]]\
 static_libs=[lsort -unique [dict get $static_by_rail $supply_name]]"
    }
    foreach supply_name $static_names {
        if {![dict exists $scaled_by_rail $supply_name]} {
            lappend static_only $supply_name
        }
    }

    puts "AUTO POWER CLASSIFICATION: scaled_cells=$scaled_count static_cells=$static_count"
    puts "AUTO POWER TARGET RAILS: $scaled_only"
    puts "AUTO POWER STATIC RAILS (unchanged): $static_only"
    if {[llength $mixed_ok]} {
        puts "AUTO POWER SHARED RAILS already at target (allowed): $mixed_ok"
    }
    if {[llength $mixed_bad]} {
        error "Scaled cell과 static SRAM/macro가 같은 power rail을 공유하지만 현재 전압이 target과 다릅니다: $mixed_bad. 같은 물리 rail을 두 전압으로 자동 분리할 수 없습니다. Target-voltage macro DB/scaling group이 필요합니다."
    }

    return [dict create \
        scaled_cells $scaled_cells \
        static_cells $static_cells \
        target_supply $scaled_supply \
        scaled_only $scaled_only \
        static_only $static_only \
        mixed_at_target $mixed_ok]
}

proc auto_scaling::run_after_restore {cfg} {
    foreach command {
        get_designs get_libs get_lib_cells current_design define_scaling_lib_group
        report_lib_groups get_supply_nets get_cells set_temperature
        set_voltage update_timing get_timing_paths add_to_collection
    } {
        if {![llength [info commands ::$command]]} {
            error "이 파일은 restore_session을 완료한 pt_shell에서만 실행할 수 있습니다."
        }
    }
    if {![sizeof_collection [get_designs -quiet *]]} {
        error "복원된 design이 없습니다. 먼저 restore_session <session_directory>를 실행하세요."
    }
    if {![sizeof_collection [get_libs -quiet *]]} {
        error "복원된 library가 없습니다. restore_session 결과를 확인하세요."
    }

    # 복원 세션의 SPEF를 그대로 사용하므로 파일 기반 SPEF 선택은 수행하지 않습니다.
    # 대신 SPEF/GPD 헤더에서 복원된 BEOL과 온도를 읽어 목표와 정확히
    # 일치하는지 확인합니다. V/T/VT는 Liberty scaling 축입니다.
    set phase_started [phase_start VERIFY_PARASITICS]
    set restored_cfg $cfg
    if {[dict exists $restored_cfg spef_template]} { dict unset restored_cfg spef_template }
    if {[dict exists $restored_cfg spef]} { dict unset restored_cfg spef }
    set parasitics [verify_restored_parasitics $restored_cfg]
    phase_done VERIFY_PARASITICS $phase_started

    set phase_started [phase_start PLAN_DESIGN_LIBRARIES]
    set plan [plan $restored_cfg]
    dict set plan restored_parasitics $parasitics
    set fixed [expr {[dict exists $plan fixed] ? [dict get $plan fixed] : ""}]
    set dt [option $cfg delay_type max]
    if {$dt ni {max min}} { error "delay_type must be max or min" }

    set original_out [file normalize [dict get $cfg out_rpt]]
    set out [file join [file dirname $original_out] "restored_[file tail $original_out]"]
    foreach suffix {"" .missing .selection.tcl .libgroups.before .libgroups .dcalc} {
        if {[file exists ${out}${suffix}]} {
            error "Output already exists: ${out}${suffix}. 기존 결과를 보존하기 위해 덮어쓰지 않습니다."
        }
    }
    file mkdir [file dirname $out]
    phase_done PLAN_DESIGN_LIBRARIES $phase_started

    set rail [option $cfg rail_name VDD]
    set gnd [option $cfg ground_name VSS]
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
        report_lib_groups -scaling -show {voltage temperature process}
    }
    write_text ${out}.libgroups.before $groups_before

    # restore session에 scaling group이 이미 있으면 그대로 재사용합니다.
    # 단, 목표 코너가 들어 있으면 leave-one-out이 아니므로 중단합니다.
    set has_existing_group [regexp -line {^Group[[:space:]]+[0-9]+} $groups_before]
    if {$has_existing_group} {
        if {[report_has_corner $groups_before $rail $target_v $target_t]} {
            error "기존 scaling group에 목표 코너 $target_v V/$target_t C가 포함되어 있습니다. 이 세션에서는 목표 DB를 제외한 scaling 결과를 만들 수 없습니다."
        }
        puts "RESTORE MODE: 기존 scaling group을 재사용합니다."
    } else {
        puts "RESTORE MODE: 목표 코너를 제외한 [llength $scaling_sets]개 scaling group을 생성합니다."
        foreach scaling_set $scaling_sets {
            set set_name [dict get $scaling_set name]
            set dbs [dict get $scaling_set dbs]
            puts "DEFINE SCALING LIBRARY SET: $set_name"
            if {[catch {define_scaling_lib_group $dbs} problem]} {
                error "Scaling group 생성 실패($set_name): $problem. 이 library set의 DB들이 같은 cell/pin 구성을 갖는지 확인하세요."
            }
        }
    }

    redirect -variable groups_after {
        report_lib_groups -scaling -show {voltage temperature process}
    }
    write_text ${out}.libgroups $groups_after
    if {[report_has_corner $groups_after $rail $target_v $target_t]} {
        error "생성된 scaling group에 목표 코너가 남아 있습니다. 결과를 사용하지 마세요: ${out}.libgroups"
    }
    verify_planned_group_coverage $plan
    phase_done PREPARE_SCALING_GROUPS $phase_started

    set phase_started [phase_start CLASSIFY_POWER_RAILS]
    set cells [get_cells -hierarchical -quiet *]
    if {![sizeof_collection $cells]} { error "현재 design에 leaf cell이 없습니다." }
    set all_supply [get_supply_nets -quiet -hierarchy *]
    set ground_supply ""
    if {![sizeof_collection $all_supply]} {
        puts "RESTORE MODE: supply net이 없어 단일 전원 domain을 생성합니다."
        create_power_domain AUTO_SCALING_TOP
        create_supply_net $rail -domain AUTO_SCALING_TOP
        create_supply_net $gnd -domain AUTO_SCALING_TOP
        set_domain_supply_net AUTO_SCALING_TOP \
            -primary_power_net $rail -primary_ground_net $gnd
        set ground_supply [get_supply_nets -quiet $gnd]
    } else {
        # Ground는 모든 domain에서 0V이므로 실제 cell 연결을 따라 자동 선택합니다.
        set ground_supply [get_supply_nets -quiet -hierarchy $gnd]
        if {![sizeof_collection $ground_supply]} {
            set ground_supply [get_supply_nets -quiet -pg_types ground -of_objects $cells]
        }
        if {![sizeof_collection $ground_supply]} {
            set ground_supply [get_supply_nets -quiet -hierarchy -pg_types ground *]
        }
    }

    # Scaling group이 실제로 적용되는 cell/library를 기준으로 target rail을
    # 고릅니다. static SRAM/macro 전용 rail과 그 cell의 온도는 복원 상태를
    # 유지합니다. 공유 rail의 전압 충돌은 변경 전에 검출합니다.
    set power_plan [classify_scaling_power $cells $target_v]
    set scaled_cells [dict get $power_plan scaled_cells]
    set power_supply [dict get $power_plan target_supply]
    puts "POWER SUPPLY NETS TO SCALE: [get_object_name $power_supply]"
    phase_done CLASSIFY_POWER_RAILS $phase_started

    set phase_started [phase_start APPLY_TARGET_VOLTAGE_TEMP]
    check_status set_temperature [list set_temperature $target_t -object_list $scaled_cells]
    check_status set_voltage [list set_voltage $target_v -object_list $power_supply]
    if {[sizeof_collection $ground_supply]} {
        puts "GROUND SUPPLY NETS: [get_object_name $ground_supply]"
        check_status set_ground [list set_voltage 0.0 -object_list $ground_supply]
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
    set paths [get_timing_paths -delay_type $dt -max_paths 1]
    if {![sizeof_collection $paths]} {
        error "목표 조건에서 timing path가 없습니다. 복원된 constraint와 analysis type을 확인하세요."
    }

    set fp [open ${out}.selection.tcl w]
    puts $fp "# restore_session 기반 scaling 선택 기록"
    set record $plan
    dict unset record fixed paths
    dict set record restored_design [get_object_name [current_design]]
    puts $fp [list set scaling_selection $record]
    close $fp

    set fp [open $out w]
    puts $fp "### SCALING TARGET process=[dict get $plan process] voltage=[dict get $plan v] temperature=[dict get $plan t] beol=[dict get $plan beol] axis=[dict get $plan mode]"
    puts $fp "### RESTORED PARASITIC corner_name=[dict get $parasitics corner_name] temperature=[dict get $parasitics temperature]"
    puts $fp ""
    close $fp

    if {$fixed ne ""} {
        set fixed_result [report_fixed_paths $out [dict get $fixed paths] \
            $dt [option $cfg pba_mode ""]]
    } else {
        set fixed_result [report_free_paths $out $dt [option $cfg free_paths 100] \
            [option $cfg pba_mode ""]]
    }
    if {![file exists $out] || [file size $out] == 0} {
        error "Timing report가 생성되지 않았습니다: $out"
    }
    phase_done GENERATE_TIMING_REPORT $phase_started

    set phase_started [phase_start VERIFY_SCALING_RESULT]
    set dcalc_text ""
    set arc_found 0
    foreach_in_collection point [get_attribute [index_collection $paths 0] points] {
        set pin [get_attribute $point object]
        if {[info exists prev_pin]} {
            set a [get_cells -quiet -of_objects $prev_pin]
            set b [get_cells -quiet -of_objects $pin]
            if {[sizeof_collection $a] == 1 && [sizeof_collection $b] == 1 &&
                [get_object_name $a] eq [get_object_name $b] &&
                [get_attribute $prev_pin direction] eq "in" &&
                [get_attribute $pin direction] eq "out"} {
                redirect -variable dcalc_text {
                    report_delay_calculation -from $prev_pin -to $pin
                }
                set arc_found 1
                break
            }
        }
        set prev_pin $pin
    }
    if {!$arc_found} { error "Scaling 사용 여부를 검증할 cell arc를 찾지 못했습니다." }
    write_text ${out}.dcalc $dcalc_text
    if {[regexp -nocase {SLG-320|DEL-012|scaling extrapolation problem|due to extrapolation in scaling} $dcalc_text]} {
        error "report_delay_calculation에서 scaling 외삽/적용 취소 오류가 검출되었습니다. 결과를 사용하지 마세요: ${out}.dcalc"
    }
    if {[string first "Scaling libraries used" $dcalc_text] < 0} {
        error "report_delay_calculation에서 scaling library 사용 증거를 찾지 못했습니다. 결과를 사용하지 마세요: ${out}.dcalc"
    }
    phase_done VERIFY_SCALING_RESULT $phase_started

    puts "DONE: restore-session scaling report = $out"
    if {$fixed ne ""} {
        puts "FIXED PATH SUMMARY: requested=[dict get $fixed_result requested] measured=[dict get $fixed_result measured] missing=[dict get $fixed_result missing]"
    } else {
        puts "FREE REPORT SUMMARY: measured=[dict get $fixed_result measured] (no fixed path file; corners are NOT comparable)"
    }
    puts "VERIFY: scaling library evidence = ${out}.dcalc"
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



proc auto_scaling::build_restore_config {} {
    foreach name {
        TARGET_PROCESS TARGET_VOLTAGE TARGET_TEMPERATURE TARGET_BEOL SCALING_AXIS
        ANALYSIS FIXED_PATH_FILE FREE_REPORT_PATHS RESULT_FOLDER POWER_NET GROUND_NET
    } {
        if {![info exists ::$name]} { error "USER SETTINGS에 $name 항목이 없습니다." }
    }

    set analysis [string tolower $::ANALYSIS]
    switch -- $analysis {
        setup { set delay_type max }
        hold  { set delay_type min }
        default { error "ANALYSIS는 setup 또는 hold여야 합니다." }
    }

    set voltage [number $::TARGET_VOLTAGE]
    set temperature [number $::TARGET_TEMPERATURE]
    set vtag [string map {. p - m} [format %.12g $voltage]]
    set ttag [string map {. p - m} [format %.12g $temperature]]
    set beol [canonical_beol $::TARGET_BEOL]
    if {$beol eq ""} {
        error "TARGET_BEOL이 비어 있거나 이름으로 사용할 문자가 없습니다."
    }
    set filename "scaled_[string toupper $::TARGET_PROCESS]_${vtag}V_${ttag}C_${beol}_[string toupper $::SCALING_AXIS]_${analysis}.rpt"

    return [dict create \
        target_process $::TARGET_PROCESS \
        target_v $voltage \
        target_t $temperature \
        target_beol $beol \
        mode $::SCALING_AXIS \
        delay_type $delay_type \
        fixed_tcl $::FIXED_PATH_FILE \
        free_paths $::FREE_REPORT_PATHS \
        rail_name $::POWER_NET \
        ground_name $::GROUND_NET \
        progress_minutes $::PROGRESS_INTERVAL_MINUTES \
        out_rpt [file join $::RESULT_FOLDER $filename]]
}

if {![info exists ::auto_scaling_restored_load_only] || !$::auto_scaling_restored_load_only} {
    set scaling_config [auto_scaling::build_restore_config]
    set scaling_result [auto_scaling::run_after_restore_monitored $scaling_config]
    puts "RUN 완료: 복원 세션 기반 scaling과 fixed-path report 생성이 끝났습니다."
}
