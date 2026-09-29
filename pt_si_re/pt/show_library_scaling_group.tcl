# Show the scaling group containing one loaded library.
#
# USER SETTINGS: enter the exact PrimeTime library name below.
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
# timing updates, or output files. No other project Tcl file is required.
# Library group voltages are not effective cell/PG-pin set_voltage overrides.
# ASCII source/output avoids UTF-8/EUC-KR source-encoding problems.

namespace eval library_scaling_group_report {}

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
        error "Expected one loaded library named '$library_name'; found 0. Use the exact library name or DB_path:lib_name extended_name, not a DB path alone or library/cell."
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
    set group [get_attribute -quiet $libraries lib_scaling_group]
    if {$group eq "" || ![sizeof_collection $group]} {
        puts "SCALING GROUP: NONE"
        puts "The library is loaded but does not belong to a scaling group in this session."
        return
    }

    # Keep the native table intact, including all named voltage rails.
    redirect -variable group_report {
        report_lib_groups -scaling -objects $libraries -nosplit \
            -show {voltage temperature process extended_name}
    }
    puts $group_report
    puts "NOTE: group library voltages, not effective cell/PG-pin voltage overrides."
    puts "For multirail libraries, compare the target against the corresponding rail."
}

# Sourcing this one file runs the read-only query immediately.
library_scaling_group_report::run $LIBRARY_NAME
