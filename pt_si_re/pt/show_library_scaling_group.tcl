# Show a loaded library's scaling group OR a scaling-script library set.
#
# USER SETTINGS: enter a library name OR the name after "library set" below.
# Use the library name shown by get_libs, not a .db path alone or a cell name.
# If the name is duplicated, use one printed extended_name: DB_path:lib_name.
set LIBRARY_NAME ""
# END USER SETTINGS
#
# Usage in pt_shell AFTER restore_session (or after a scaling run):
#   source /absolute/path/to/pt/show_library_scaling_group.tcl
#
# Output: the selected library's scaling group, all member library names,
# process, temperature, voltage (including individual multirail values), and
# extended names to distinguish libraries with the same internal name.
# This is the CURRENT group. Run in the same session that showed the warning.
# A group created during scaling will not exist in a fresh restore unless saved.
#
# Read-only: no library loading, group changes, voltage/temperature changes,
# timing updates, or output files. Exact library lookup is independent.
# Library-set lookup reuses auto_scaling::catalog already defined by the
# scaling Tcl in the SAME session, even when scaling stopped with an error.
# It does NOT source the scaling Tcl or restart scaling. It shows all loaded
# members of the set separately from any CURRENT PrimeTime scaling group.
# Library group voltages are not effective cell/PG-pin set_voltage overrides.
# ASCII source/output avoids UTF-8/EUC-KR source-encoding problems.

namespace eval library_scaling_group_report {}

proc library_scaling_group_report::show_current_group {libraries seen_name} {
    upvar 1 $seen_name seen
    set group [get_attribute -quiet $libraries lib_scaling_group]
    if {$group eq "" || ![sizeof_collection $group]} { return 0 }
    # lib_scaling_group can return the OTHER libraries, excluding this one.
    set key [list [get_attribute $libraries extended_name]]
    foreach_in_collection member $group {
        lappend key [get_attribute $member extended_name]
    }
    set key [lsort -unique $key]
    if {[dict exists $seen $key]} { return 1 }
    dict set seen $key 1
    redirect -variable group_report {
        report_lib_groups -scaling -objects $libraries -nosplit \
            -show {voltage temperature process extended_name}
    }
    puts $group_report
    return 1
}

# Use the very same family parser as the failed/completed scaling run.
# Never replace arbitrary name fragments with wildcards to guess a set.
proc library_scaling_group_report::show_library_set {set_name} {
    if {![llength [info commands ::auto_scaling::catalog]]} {
        error "No exact loaded library named '$set_name'; found 0. For a library-set name, source this query in the SAME pt_shell where run_scaling_after_restore.tcl was already run. Do not restart scaling just to query."
    }
    set cfg [dict create mode V]
    if {[info exists ::SCALING_AXIS]} { dict set cfg mode $::SCALING_AXIS }
    if {[info exists ::TARGET_PROCESS]} { dict set cfg target_process $::TARGET_PROCESS }
    if {[info exists ::scaling_config]} { set cfg $::scaling_config }
    set process ""
    if {[dict exists $cfg target_process]} {
        set process [string toupper [dict get $cfg target_process]]
    }
    puts "LIBRARY SET LOOKUP: using the scaling script's loaded-library catalog (read-only)."
    set catalog [::auto_scaling::catalog $cfg]
    set members {}
    foreach row [dict get $catalog rows] {
        if {![string equal -nocase [dict get $row family] $set_name]} { continue }
        if {$process ne "" && [dict get $row process] ne $process} { continue }
        lappend members $row
    }
    if {![llength $members]} {
        error "No exact loaded library or scaling-script library set named '$set_name'; found 0 (process filter='$process'). Copy only the name inside the quotes after library set, without quotes or the rest of the error message."
    }
    puts "SELECTED LIBRARY SET: [dict get [lindex $members 0] family]"
    puts "LOADED SET MEMBERS: [llength $members] | process_filter=$process"
    if {[dict exists $cfg target_v] && [dict exists $cfg target_t]} {
        puts "SCALING RUN TARGET: voltage=[dict get $cfg target_v] V temperature=[dict get $cfg target_t] C axis=[dict get $cfg mode]"
    }
    # The catalog includes target and other-temperature libraries that the
    # scaling planner may exclude. These are NOT claimed to be active inputs.
    puts "NOTE: loaded set members below are NOT necessarily active scaling inputs."
    foreach row $members {
        puts "LIB=[dict get $row lib_name] | voltage=[dict get $row v] V | temperature=[dict get $row t] C | process=[dict get $row process]"
        puts "  DB=[dict get $row file]"
    }
    puts "CURRENT PRIMETIME SCALING GROUPS FOR THESE MEMBERS:"
    set seen [dict create]
    set no_group_count 0
    set unresolved_count 0
    foreach row $members {
        set extended_name "[dict get $row file]:[dict get $row lib_name]"
        set library [get_libs -quiet -exact [list $extended_name]]
        if {[sizeof_collection $library] != 1} {
            incr unresolved_count
            puts "CURRENT GROUP: UNAVAILABLE | $extended_name"
            continue
        }
        if {![show_current_group $library seen]} {
            incr no_group_count
            puts "CURRENT GROUP: NONE | $extended_name"
        }
    }
    puts "SET SUMMARY: members=[llength $members] current_groups=[dict size $seen] ungrouped=$no_group_count unresolved=$unresolved_count"
    puts "NOTE: catalog voltages use the scaling script's PVT parser; the native group tables show actual group rail voltages. Neither shows effective cell/PG-pin overrides."
}

proc library_scaling_group_report::run {library_name} {
    set library_name [string trim $library_name]
    if {$library_name eq ""} {
        error "Set LIBRARY_NAME at the top of show_library_scaling_group.tcl, then source it again."
    }
    foreach command {get_libs sizeof_collection foreach_in_collection get_object_name get_attribute report_lib_groups redirect} {
        if {![llength [info commands $command]]} {
            error "PrimeTime command '$command' is missing. Source this file in pt_shell after restore_session."
        }
    }

    # Exact lookup keeps special characters and long names literal.
    set libraries [get_libs -quiet -exact [list $library_name]]
    set count [sizeof_collection $libraries]
    if {$count == 0} {
        show_library_set $library_name
        return
    }
    if {$count > 1} {
        set choices {}
        foreach_in_collection lib $libraries {
            lappend choices [get_attribute $lib extended_name]
        }
        error "Library name '$library_name' matches $count loaded libraries. Set LIBRARY_NAME to one exact extended_name below:\n  [join $choices "\n  "]"
    }
    puts "SELECTED LIBRARY: [get_object_name $libraries]"

    # Membership comes from PrimeTime, not filename/family-name parsing.
    set seen [dict create]
    if {![show_current_group $libraries seen]} {
        puts "SCALING GROUP: NONE"
        puts "The library is loaded but does not belong to a scaling group in this session."
        return
    }

    puts "NOTE: group library voltages, not effective cell/PG-pin voltage overrides."
    puts "For multirail libraries, compare the target against the corresponding rail."
}

# Sourcing this one file runs the read-only query immediately.
library_scaling_group_report::run $LIBRARY_NAME
