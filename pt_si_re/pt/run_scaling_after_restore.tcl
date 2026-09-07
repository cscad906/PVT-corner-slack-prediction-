# PrimeTime restore_session 직후 실행하는 scaling 전용 스크립트
#
# 사용 순서:
#   pt_shell
#   restore_session /path/to/saved_session
#   source /home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/pt/run_scaling_after_restore.tcl
#
# 목표 코너, scaling 방향, fixed path와 결과 폴더는 같은 디렉터리의
# check_scaling.tcl 위쪽 USER SETTINGS에서 설정합니다.
# 이 파일은 netlist/SDC/SPEF를 다시 읽거나 design을 다시 link하지 않습니다.

set auto_scaling_script_dir [file dirname [file normalize [info script]]]
set ::auto_scaling_load_only 1
source [file join $auto_scaling_script_dir check_scaling.tcl]
unset ::auto_scaling_load_only

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

if {![info exists ::auto_scaling_restored_load_only] || !$::auto_scaling_restored_load_only} {
    set scaling_config [auto_scaling::build_config]
    set scaling_result [auto_scaling::run_after_restore $scaling_config]
    puts "RUN 완료: 복원 세션 기반 scaling과 fixed-path report 생성이 끝났습니다."
}
