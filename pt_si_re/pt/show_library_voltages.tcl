# Show voltage/temperature values defined in all currently loaded libraries.
#
# Run in pt_shell AFTER restoring the session:
#   restore_session /absolute/path/to/session
#   source /absolute/path/to/pt/show_library_voltages.tcl
#
# No user settings or other project Tcl files are required.
# This script reads library reports only. It does not set voltage/temperature,
# change library groups, update timing, or write any files.
#
# IMPORTANT: These are library Operating Conditions values, not effective
# cell/PG-pin voltages after set_voltage. Multiple conditions are all listed;
# this script does not guess which condition is active or expand all PG rails.
# ASCII source/output labels avoid UTF-8/EUC-KR source-encoding problems.

namespace eval library_voltage_report {}

# Read the Operating Conditions table: name, process, temperature, voltage.
# A missing value is unavailable, not zero. Header/other table rows are skipped.
proc library_voltage_report::read_conditions {report_text} {
    set in_table 0
    set conditions {}
    foreach line [split $report_text "\n"] {
        set line [string trim $line]
        if {$line eq "Operating Conditions:"} {
            set in_table 1
            continue
        }
        if {!$in_table} { continue }
        if {$line eq "" && [llength $conditions]} { break }
        set fields [regexp -all -inline {\S+} $line]
        if {[llength $fields] < 4} { continue }
        if {![string is double -strict [lindex $fields 1]] ||
            ![string is double -strict [lindex $fields 2]] ||
            ![string is double -strict [lindex $fields 3]]} { continue }
        lappend conditions [dict create name [lindex $fields 0] \
            temperature [lindex $fields 2] voltage [lindex $fields 3]]
    }
    return $conditions
}

# Query each loaded library without changing the restored design or timing.
proc library_voltage_report::run {} {
    foreach command {get_libs sizeof_collection foreach_in_collection get_object_name report_lib redirect} {
        if {![llength [info commands $command]]} {
            error "PrimeTime command '$command' is missing. Source this file in pt_shell after restore_session."
        }
    }
    set libraries [get_libs -quiet *]
    set loaded_count [sizeof_collection $libraries]
    set listed_count 0
    set row_count 0
    puts "LIBRARY VOLTAGE LIST: loaded=$loaded_count"
    puts "NOTE: library Operating Conditions values; not cell set_voltage overrides."
    foreach_in_collection lib $libraries {
        set lib_name [get_object_name $lib]
        if {[catch {
            redirect -variable report_text { report_lib -nosplit $lib_name }
        } reason]} {
            puts "$lib_name : voltage=UNAVAILABLE (report_lib failed: $reason)"
            continue
        }
        set conditions [read_conditions $report_text]
        if {![llength $conditions]} {
            puts "$lib_name : voltage=UNAVAILABLE (no readable Operating Conditions row)"
            continue
        }
        incr listed_count
        foreach condition $conditions {
            puts [format "%s : voltage=%s V temperature=%s C condition=%s" \
                $lib_name [dict get $condition voltage] \
                [dict get $condition temperature] [dict get $condition name]]
            incr row_count
        }
    }
    puts "LIBRARY VOLTAGE SUMMARY: loaded=$loaded_count listed=$listed_count rows=$row_count unavailable=[expr {$loaded_count-$listed_count}]"
    return [dict create loaded $loaded_count listed $listed_count rows $row_count \
        unavailable [expr {$loaded_count-$listed_count}]]
}

# Sourcing this one file runs the read-only query immediately.
library_voltage_report::run
