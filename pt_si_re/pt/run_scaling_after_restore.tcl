# PrimeTime restore_session 직후 실행하는 독립형 scaling 스크립트
#
# 사용 순서:
#   pt_shell
#   restore_session /path/to/saved_session
#   source /home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/pt/run_scaling_after_restore.tcl
#
# 현재 restore session에 이미 로드된 design/library/SDC/SPEF만 사용합니다.
# 이 파일은 read_db/read_verilog/link_design/read_sdc/read_parasitics를 실행하지 않습니다.

# ======================= USER SETTINGS ========================

# 목표 코너와 보간 방향
set TARGET_PROCESS      "SSPG"    ;# report_lib에 표시되는 실제 공정 이름(예: TT, SSPG)
set TARGET_VOLTAGE      0.75      ;# Volt
set TARGET_TEMPERATURE  25        ;# Celsius. 영하 40도는 -40
set SCALING_AXIS        "V"       ;# V / T / VT

# 분석 종류
set ANALYSIS            "setup"   ;# setup / hold

# 1_union.py가 만든 fixed path 파일
set FIXED_PATH_FILE "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/example/round1/corners/fixed_paths.tcl"

# 결과 폴더
set RESULT_FOLDER "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/pt/auto_scaling_output"

# 복원 세션의 단일 전원 이름
set POWER_NET  "VDD"
set GROUND_NET "VSS"

# ===================== END USER SETTINGS =====================
# 아래 구현부는 수정하지 않아도 됩니다.
namespace eval auto_scaling {}
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

proc auto_scaling::report_family {lib path process} {
    set family [get_attribute $lib full_name]
    if {$family eq ""} { set family [file rootname [file tail $path]] }
    set family [string tolower $family]
    set family [string map [list [string tolower $process] PROCESS] $family]
    regsub -all {[0-9]+(?:[p.][0-9]+)?v} $family {VOLTAGE} family
    regsub -all {(?:m|-)?[0-9]+(?:[p.][0-9]+)?c} $family {TEMPERATURE} family
    return $family
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
            set family [report_family $lib $path $process]
        }
    }
    set lib_name [get_attribute $lib full_name]
    return [dict create file $path process [string toupper $process] \
        v [number $v] t [number $t] family $family lib_name $lib_name]
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

proc auto_scaling::plan {cfg} {
    set process [string toupper [need $cfg target_process]]
    set tv [number [need $cfg target_v]]
    set tt [number [need $cfg target_t]]
    set mode [string toupper [need $cfg mode]]
    if {[lsearch -exact [list V T VT] $mode] < 0} {
        error "SCALING_AXIS must be V, T, or VT"
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
    set family [option $cfg family ""]
    if {$family eq ""} {
        if {[llength $families] == 1} {
            set family [lindex $families 0]
        } else {
            set used_result [family_used_by_design $rows $families]
            set used_matches [dict get $used_result family_matches]
            if {[llength $used_matches] == 1} {
                set family [lindex $used_matches 0]
                puts "AUTO-SELECTED LIBRARY FAMILY USED BY DESIGN: $family"
            } else {
                error "Library family selection is ambiguous. PVT candidates: $families; design-used matches: $used_matches; design-used library names: [dict get $used_result used_library_names]"
            }
        }
    }
    set pool {}
    set excluded {}
    foreach row $rows {
        if {[dict get $row process] ne $process || [dict get $row family] ne $family} {
            continue
        } elseif {[same [dict get $row v] $tv] && [same [dict get $row t] $tt]} {
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
                error "Need exactly one library at $process/$v V/$t C; found [llength $matches]. Missing rectangle corner or duplicate revisions."
            }
            lappend selected [lindex $matches 0]
        }
    }

    set result [dict create]
    dict set result process $process
    dict set result v $tv
    dict set result t $tt
    dict set result mode $mode
    dict set result family $family
    dict set result selected $selected
    dict set result excluded $excluded
    dict set result catalog $rows
    dict set result shadows [dict get $cat shadows]
    if {[option $cfg fixed_tcl ""] ne ""} {
        dict set result fixed [read_fixed [dict get $cfg fixed_tcl] [option $cfg delay_type max]]
    }

    puts "TARGET: $process  $tv V  $tt C; mode=$mode; family=$family"
    foreach row $excluded {
        puts "EXCLUDED TARGET: [dict get $row file]"
    }
    if {![llength $excluded]} {
        puts "TARGET LIBRARY: absent"
    }
    foreach row $selected {
        puts "SCALING INPUT: [dict get $row file]"
    }
    if {[dict exists $result fixed]} {
        puts "FIXED PATHS: [dict get $result fixed count] from [dict get $result fixed file]"
    }
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
        if {[catch {set row [corner $lib $path $overrides]} reason]} {
            lappend ignored [list $path $reason]
            continue
        }
        lappend rows $row
    }
    if {![llength $rows]} {
        set detail ""
        foreach item [lrange $ignored 0 2] {
            append detail "\n  [lindex $item 0]: [lindex $item 1]"
        }
        error "Restore session의 파일명과 report_lib에서 P/V/T를 식별할 library를 찾지 못했습니다.$detail"
    }
    puts "LOADED PVT LIBRARIES: [llength $rows]"
    if {[llength $ignored]} {
        puts "IGNORED NON-PVT LIBRARIES: [llength $ignored]"
    }
    return [dict create rows $rows shadows {}]
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
    set measured 0
    set missing {}
    set idx 0
    foreach item $paths {
        incr idx
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
        if {$count == 1} { incr measured } else { lappend missing $idx }
        redirect -append $out_file {
            puts "### FIXED_PATH idx=$idx key=$key"
            puts $text
            puts ""
        }
    }
    puts "FIXED PATHS RESULT: requested=$idx measured=$measured missing=[llength $missing]"
    if {[llength $missing]} {
        error "Incomplete fixed-path report: [llength $missing] paths failed; idx=$missing. Inspect $out_file; no replacement paths were selected."
    }
}

proc auto_scaling::report_has_corner {text rail voltage temperature} {
    foreach line [split $text "\n"] {
        if {![regexp {^\s+\S+\s+(-?[0-9]+(?:\.[0-9]+)?)\s+\{([^\n]*)\}} $line -> found_t rails]} {
            continue
        }
        set pattern [format {%s:([-+]?[0-9]+(?:\.[0-9]+)?)} $rail]
        if {[regexp $pattern $rails -> found_v] &&
            [same [number $found_v] $voltage] && [same [number $found_t] $temperature]} {
            return 1
        }
    }
    return 0
}

proc auto_scaling::write_text {path contents} {
    set fp [open $path w]
    puts -nonewline $fp $contents
    close $fp
}

proc auto_scaling::run_after_restore {cfg} {
    foreach command {
        get_designs get_libs current_design define_scaling_lib_group
        report_lib_groups get_supply_nets get_cells set_temperature
        set_voltage update_timing get_timing_paths
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
    set restored_cfg $cfg
    if {[dict exists $restored_cfg spef_template]} { dict unset restored_cfg spef_template }
    if {[dict exists $restored_cfg spef]} { dict unset restored_cfg spef }
    set plan [plan $restored_cfg]
    set fixed [dict get $plan fixed]
    set dt [option $cfg delay_type max]
    if {$dt ni {max min}} { error "delay_type must be max or min" }

    set original_out [file normalize [dict get $cfg out_rpt]]
    set out [file join [file dirname $original_out] "restored_[file tail $original_out]"]
    foreach suffix {"" .selection.tcl .libgroups.before .libgroups .dcalc} {
        if {[file exists ${out}${suffix}]} {
            error "Output already exists: ${out}${suffix}. 기존 결과를 보존하기 위해 덮어쓰지 않습니다."
        }
    }
    file mkdir [file dirname $out]

    set rail [option $cfg rail_name VDD]
    set gnd [option $cfg ground_name VSS]
    set target_v [dict get $plan v]
    set target_t [dict get $plan t]
    set dbs {}
    foreach row [dict get $plan selected] { lappend dbs [dict get $row file] }

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
        puts "RESTORE MODE: 목표 코너를 제외한 scaling group을 생성합니다."
        if {[catch {define_scaling_lib_group $dbs} problem]} {
            error "Scaling group 생성 실패: $problem. 복원 세션의 link library가 선택된 입력 DB 중 하나인지 확인하세요."
        }
    }

    redirect -variable groups_after {
        report_lib_groups -scaling -show {voltage temperature process}
    }
    write_text ${out}.libgroups $groups_after
    if {[report_has_corner $groups_after $rail $target_v $target_t]} {
        error "생성된 scaling group에 목표 코너가 남아 있습니다. 결과를 사용하지 마세요: ${out}.libgroups"
    }

    set cells [get_cells -hierarchical -quiet *]
    if {![sizeof_collection $cells]} { error "현재 design에 leaf cell이 없습니다." }
    set all_supply [get_supply_nets -quiet *]
    set power_supply [get_supply_nets -quiet $rail]
    if {![sizeof_collection $all_supply]} {
        puts "RESTORE MODE: supply net이 없어 단일 전원 domain을 생성합니다."
        create_power_domain AUTO_SCALING_TOP
        create_supply_net $rail -domain AUTO_SCALING_TOP
        create_supply_net $gnd -domain AUTO_SCALING_TOP
        set_domain_supply_net AUTO_SCALING_TOP \
            -primary_power_net $rail -primary_ground_net $gnd
        set power_supply [get_supply_nets -quiet $rail]
    } elseif {[sizeof_collection $power_supply] != 1} {
        set available [get_object_name $all_supply]
        error "POWER_NET '$rail'을 하나로 찾을 수 없습니다. 복원 세션 supply nets: $available"
    }

    check_status set_temperature [list set_temperature $target_t -object_list $cells]
    check_status set_voltage [list set_voltage $target_v -object_list $power_supply]
    set ground_supply [get_supply_nets -quiet $gnd]
    if {[sizeof_collection $ground_supply] == 1} {
        check_status set_ground [list set_voltage 0.0 -object_list $ground_supply]
    }
    check_status update_timing {update_timing -full}

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

    report_fixed_paths $out [dict get $fixed paths] $dt [option $cfg pba_mode ""]
    if {![file exists $out] || [file size $out] == 0} {
        error "Fixed-path timing report가 생성되지 않았습니다: $out"
    }

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
    if {[string first "Scaling libraries used" $dcalc_text] < 0} {
        error "report_delay_calculation에서 scaling library 사용 증거를 찾지 못했습니다. 결과를 사용하지 마세요: ${out}.dcalc"
    }

    puts "DONE: restore-session scaling report = $out"
    puts "VERIFY: scaling library evidence = ${out}.dcalc"
    return $out
}



proc auto_scaling::build_restore_config {} {
    foreach name {
        TARGET_PROCESS TARGET_VOLTAGE TARGET_TEMPERATURE SCALING_AXIS
        ANALYSIS FIXED_PATH_FILE RESULT_FOLDER POWER_NET GROUND_NET
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
    set filename "scaled_[string toupper $::TARGET_PROCESS]_${vtag}V_${ttag}C_[string toupper $::SCALING_AXIS]_${analysis}.rpt"

    return [dict create \
        target_process $::TARGET_PROCESS \
        target_v $voltage \
        target_t $temperature \
        mode $::SCALING_AXIS \
        delay_type $delay_type \
        fixed_tcl $::FIXED_PATH_FILE \
        rail_name $::POWER_NET \
        ground_name $::GROUND_NET \
        out_rpt [file join $::RESULT_FOLDER $filename]]
}

if {![info exists ::auto_scaling_restored_load_only] || !$::auto_scaling_restored_load_only} {
    set scaling_config [auto_scaling::build_restore_config]
    set scaling_result [auto_scaling::run_after_restore $scaling_config]
    puts "RUN 완료: 복원 세션 기반 scaling과 fixed-path report 생성이 끝났습니다."
}
