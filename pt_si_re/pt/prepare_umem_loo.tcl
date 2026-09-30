# Read-only u_mem VDDPE LOO preparation for a restore session WITH native groups.
# Edit USER SETTINGS in run_scaling_after_restore.tcl first, then:
#   restore_session /path/to/current_session
#   source /path/to/pt/prepare_umem_loo.tcl
# This writes RESULT_FOLDER/umem_loo_group.tcl. It does not change the session.
# The generated group can only be defined in a session where the u_mem group
# has not yet been created. Source run_umem_loo_after_restore.tcl there.

set ::auto_scaling_restored_load_only 1
source [file join [file dirname [info script]] run_scaling_after_restore.tcl]
unset ::auto_scaling_restored_load_only

namespace eval umem_loo {}

proc umem_loo::patterns {raw} {
    set result {}
    foreach item [split [string trim $raw] ,] {
        set item [string trim $item]
        if {$item eq ""} { error "UML-001: Set nonempty VDDPE_SCALING_NAME_PATTERNS." }
        lappend result $item
    }
    return $result
}

proc umem_loo::parse_group {report} {
    set rows [dict create]
    foreach line [split $report "\n"] {
        if {![regexp {^\s*(\S+)\s+([-+]?[0-9]+(?:\.[0-9]+)?)\s+\{([^\}]*)\}} \
                $line -> name temperature rails]} { continue }
        if {![regexp -nocase {(?:^|[[:space:]])VDDPE:([-+]?[0-9]+(?:\.[0-9]+)?)} \
                $rails -> vddpe]} {
            error "UML-002: No VDDPE voltage in native group row: $line"
        }
        if {[dict exists $rows $name]} {
            error "UML-003: Duplicate native group row for $name."
        }
        dict set rows $name [dict create temperature $temperature vddpe $vddpe rails $rails]
    }
    if {![dict size $rows]} { error "UML-004: No multirail rows in report_lib_groups output." }
    return $rows
}

# A group remains intact except for every member at target T/VDDPE. Never
# borrow a higher voltage from a different group or relink a target-linked cell.
proc umem_loo::select_members {members report linked target_t target_vddpe} {
    set rows [parse_group $report]
    set kept {}
    set excluded {}
    set voltages {}
    foreach member $members {
        lassign $member name db
        if {![dict exists $rows $name]} {
            error "UML-005: Native group report omits member $name ($db)."
        }
        set row [dict get $rows $name]
        set at_temperature [auto_scaling::report_number_may_match \
            [dict get $row temperature] $target_t]
        set at_target [expr {$at_temperature && [auto_scaling::report_number_may_match \
            [dict get $row vddpe] $target_vddpe]}]
        if {$at_target} {
            lappend excluded $member
        } else {
            lappend kept $member
            if {$at_temperature} {
                lappend voltages [auto_scaling::number [dict get $row vddpe]]
            }
        }
    }
    if {![llength $excluded]} {
        error "UML-006: No target VDDPE=$target_vddpe V/$target_t C member was found. The native group is already target-excluded or the report is incomplete."
    }
    foreach name $linked {
        set found 0
        foreach member $kept {
            if {[lindex $member 0] eq $name} { set found 1; break }
        }
        if {!$found} {
            error "UML-007: Linked u_mem library $name is the excluded target. A source-linked restore session is required; this script will not relink it."
        }
    }
    if {[llength $kept] < 2} {
        error "UML-008: Only [llength $kept] library remains after target exclusion; 1-D PT scaling requires at least two."
    }
    if {[catch {set pair [auto_scaling::bracket $voltages $target_vddpe VDDPE]} reason]} {
        error "UML-009: No same-temperature VDDPE interpolation bracket after target exclusion: $reason; remaining=$voltages"
    }
    return [dict create kept $kept excluded $excluded bracket $pair]
}

proc umem_loo::prepare {} {
    set cfg [auto_scaling::build_restore_config]
    set target [auto_scaling::number [auto_scaling::need $cfg target_vddpe]]
    set temperature [dict get $cfg target_t]
    set fixed [auto_scaling::read_fixed [dict get $cfg fixed_tcl] [dict get $cfg delay_type]]
    set cells [auto_scaling::fixed_path_cells $fixed]
    set lib_cells [get_attribute $cells lib_cell]
    if {[sizeof_collection $cells] != [sizeof_collection $lib_cells]} {
        error "UML-010: Cannot map all fixed-path cells to linked libraries."
    }
    set patterns [patterns [dict get $cfg vddpe_name_patterns]]
    set selected [dict create]
    foreach name [get_object_name $cells] lib_cell [get_object_name $lib_cells] {
        set library [lindex [split $lib_cell /] 0]
        foreach pattern $patterns {
            if {[string match -nocase $pattern $name] ||
                [string match -nocase $pattern $library]} {
                dict set selected $name $library
                break
            }
        }
    }
    if {![dict size $selected]} {
        error "UML-011: No fixed-path u_mem cell matches VDDPE_SCALING_NAME_PATTERNS=$patterns."
    }
    set records [dict create]
    dict for {name expected_library} $selected {
        set cell [get_cells -quiet -exact $name]
        set found 0
        foreach_in_collection pg [get_pg_pins -of_objects $cell] {
            if {[string equal -nocase [get_attribute $pg pin_name] VDDPE] &&
                [get_attribute $pg type] eq "primary_power"} { set found 1; break }
        }
        if {!$found} { error "UML-012: $name has no primary_power VDDPE PG pin." }
        set lib [get_libs -quiet -of_objects [get_lib_cells -quiet -of_objects $cell]]
        if {[sizeof_collection $lib] != 1} { error "UML-013: $name has no unique linked library." }
        set linked_name [get_attribute $lib full_name]
        if {$linked_name ne $expected_library} {
            error "UML-014: Linked library changed for $name: $expected_library -> $linked_name"
        }
        set group [get_attribute -quiet $lib lib_scaling_group]
        if {$group eq "" || ![sizeof_collection $group]} {
            error "UML-015: $name has no active native scaling group to inspect."
        }
        set members {}
        foreach_in_collection member [add_to_collection $group $lib] {
            set db [get_attribute -quiet $member source_file_name]
            if {$db eq ""} { error "UML-016: No source DB for [get_attribute $member full_name]." }
            lappend members [list [get_attribute $member full_name] [file normalize $db]]
        }
        set members [lsort -unique $members]
        set key $members
        if {[dict exists $records $key]} {
            dict lappend records $key linked $linked_name
            continue
        }
        redirect -variable report {
            report_lib_groups -scaling -objects $lib -nosplit -show {voltage temperature process}
        }
        dict set records $key [dict create members $members linked [list $linked_name] report $report]
    }
    set plans {}
    dict for {key record} $records {
        set selected_members [select_members [dict get $record members] \
            [dict get $record report] [lsort -unique [dict get $record linked]] \
            $temperature $target]
        lappend plans [dict merge $record $selected_members]
    }
    set output [file join [file normalize $::RESULT_FOLDER] umem_loo_group.tcl]
    file mkdir [file dirname $output]
    set fp [open $output w]
    puts $fp "# Generated u_mem LOO group. Source only in a session without the original u_mem group."
    puts $fp "# Target VDDPE=$target V temperature=$temperature C; source session must link a retained DB."
    puts $fp [list set ::umem_loo_group_plan [dict create \
        target_vddpe $target target_t $temperature fixed_tcl [file normalize [dict get $cfg fixed_tcl]] \
        design [get_object_name [current_design]] groups $plans]]
    puts $fp {if {![auto_scaling::same [auto_scaling::number $::TARGET_VDDPE_VOLTAGE] [dict get $::umem_loo_group_plan target_vddpe]] ||
    ![auto_scaling::same [auto_scaling::number $::TARGET_TEMPERATURE] [dict get $::umem_loo_group_plan target_t]]} {
    error "UML-017: Generated u_mem LOO group target does not match current USER SETTINGS."
}}
    puts $fp {if {[get_object_name [current_design]] ne [dict get $::umem_loo_group_plan design] ||
    [file normalize $::FIXED_PATH_FILE] ne [dict get $::umem_loo_group_plan fixed_tcl]} {
    error "UML-018: Generated group design/fixed-path source does not match this session."
}}
    puts $fp {foreach_in_collection lib [get_libs -quiet *] {
    set db [get_attribute -quiet $lib source_file_name]
    if {$db eq ""} { continue }
    foreach record [dict get $::umem_loo_group_plan groups] {
        foreach member [dict get $record members] {
            if {[file normalize $db] ne [lindex $member 1]} { continue }
            set active [get_attribute -quiet $lib lib_scaling_group]
            if {$active ne "" && [sizeof_collection $active]} {
                error "UML-019: Original u_mem group is already active for $db. Restore a session before this group was defined."
            }
        }
    }
}}
    puts $fp {foreach record [dict get $::umem_loo_group_plan groups] {
    set dbs {}
    foreach member [dict get $record kept] { lappend dbs [lindex $member 1] }
    set failed [catch {define_scaling_lib_group $dbs} status]
    if {$failed || $status ne "1"} {
        error "UML-021: Target-excluded u_mem group definition failed: status=$status"
    }
    puts "U_MEM LOO GROUP DEFINED: input_dbs=[llength $dbs] excluded=[dict get $record excluded] bracket=[dict get $record bracket]"
}}
    close $fp
    puts "U_MEM LOO PREPARED: $output"
    foreach record $plans {
        puts "U_MEM LOO PLAN: linked=[lsort -unique [dict get $record linked]] excluded=[dict get $record excluded] bracket=[dict get $record bracket]"
    }
    puts "CURRENT SESSION UNCHANGED: the generated group cannot be defined over its active original group."
    return $output
}

if {![info exists ::umem_loo_prepare_load_only] || !$::umem_loo_prepare_load_only} {
    umem_loo::prepare
}
