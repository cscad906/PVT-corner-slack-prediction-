# Show a loaded library's scaling group OR a scaling-script library set.
#
# USER SETTINGS: blank = read the failed library-set name from the current run log.
# Or enter an exact library name OR the name after "library set" below.
# Use the library name shown by get_libs, not a .db path alone or a cell name.
# If the name is duplicated, use one printed extended_name: DB_path:lib_name.
set LIBRARY_NAME ""
# 0 = compact catalog audit; 1 = print every loaded library and its lookup/input reason.
# This setting applies to library-set lookup, not exact-library group lookup.
set SHOW_ALL_LOADED_LIBRARIES 0
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

# Explain catalog/filter decisions without changing the scaling inputs. A row
# from another set is NOT a compatible input merely because its V is useful.
proc library_scaling_group_report::catalog_row_reason {row set_name cfg} {
    if {![string equal -nocase [dict get $row family] $set_name]} {
        return [list OTHER_LIBRARY_SET NOT_EVALUATED]
    }
    if {[dict exists $cfg target_process] && [dict get $cfg target_process] ne "" &&
        [dict get $row process] ne [string toupper [dict get $cfg target_process]]} {
        return [list OTHER_PROCESS NOT_EVALUATED]
    }
    if {![dict exists $cfg target_v] || ![dict exists $cfg target_t] ||
        [string toupper [dict get $cfg mode]] ne "V"} {
        return [list SET_MEMBER NOT_EVALUATED]
    }
    if {abs([dict get $row t] - [dict get $cfg target_t]) >= 1e-8} {
        return [list SET_MEMBER OTHER_TEMPERATURE]
    }
    set fixed_sets {}
    if {[dict exists $cfg fixed_library_set]} {
        if {[llength [info commands ::auto_scaling::resolve_fixed_families]]} {
            set fixed_sets [::auto_scaling::resolve_fixed_families \
                [dict get $cfg fixed_library_set] [dict get $cfg catalog_families] 0]
        } elseif {[string equal -nocase [dict get $cfg fixed_library_set] $set_name]} {
            set fixed_sets [list [dict get $row family]]
        }
    }
    if {[lsearch -exact $fixed_sets [dict get $row family]] >= 0} {
        if {[dict exists $cfg fixed_library_voltage] &&
            [string equal -nocase [dict get $cfg fixed_library_voltage] nearest]} {
            return [list SET_MEMBER NEAREST_DB_CANDIDATE]
        }
        return [list SET_MEMBER FIXED_RESTORE_DB]
    }
    if {abs([dict get $row v] - [dict get $cfg target_v]) < 1e-8} {
        return [list SET_MEMBER EXCLUDED_TARGET_POINT]
    }
    return [list SET_MEMBER V_INPUT_CANDIDATE]
}

proc library_scaling_group_report::show_catalog_audit {catalog set_name cfg} {
    set verbose 0
    if {[info exists ::SHOW_ALL_LOADED_LIBRARIES]} {
        if {![string is boolean -strict $::SHOW_ALL_LOADED_LIBRARIES]} {
            error "LG-002: SHOW_ALL_LOADED_LIBRARIES must be 0 or 1."
        }
        set verbose [expr {$::SHOW_ALL_LOADED_LIBRARIES ? 1 : 0}]
    }
    set counts [dict create SET_MEMBER 0 OTHER_LIBRARY_SET 0 OTHER_PROCESS 0]
    set input_counts [dict create V_INPUT_CANDIDATE 0 OTHER_TEMPERATURE 0 \
        EXCLUDED_TARGET_POINT 0 NEAREST_DB_CANDIDATE 0 FIXED_RESTORE_DB 0 NOT_EVALUATED 0]
    set represented [dict create]
    set catalog_paths [dict create]
    set voltages {}
    set rows [dict get $catalog rows]
    foreach row $rows {
        dict set represented [list [dict get $row file] [dict get $row lib_name]] 1
        dict set catalog_paths [dict get $row file] 1
        lappend voltages [dict get $row v]
        lassign [catalog_row_reason $row $set_name $cfg] lookup input
        dict incr counts $lookup
        dict incr input_counts $input
    }
    set ignored {}
    if {[dict exists $catalog ignored]} { set ignored [dict get $catalog ignored] }
    foreach row $ignored {
        dict set represented [list [dict get $row path] [dict get $row lib_name]] 1
        dict set catalog_paths [dict get $row path] 1
    }

    # The scaling catalog deduplicates source_file_name. Check the raw loaded
    # objects too, so another internal library in the same DB is not hidden.
    # No report_lib, PG-pin query, or timing update is added by this audit.
    set loaded [get_libs -quiet *]
    set skipped {}
    foreach_in_collection lib $loaded {
        set path [get_attribute $lib source_file_name]
        set name [get_attribute $lib full_name]
        if {[dict exists $represented [list $path $name]]} { continue }
        if {$path eq ""} {
            set reason NO_SOURCE_FILE
        } elseif {[dict exists $catalog_paths $path]} {
            set reason SOURCE_PATH_REUSED
        } else {
            set reason NOT_IN_CATALOG
        }
        lappend skipped [dict create lib_name $name path $path reason $reason]
    }
    puts "CATALOG AUDIT: raw_loaded=[sizeof_collection $loaded] parsed=[llength $rows] unparsed=[llength $ignored] not_cataloged=[llength $skipped]"
    puts "CATALOG VOLTAGES (all parsed sets/processes/temperatures; NOT scaling inputs): [lsort -real -unique $voltages]"
    puts "SET LOOKUP AUDIT: members=[dict get $counts SET_MEMBER] other_set=[dict get $counts OTHER_LIBRARY_SET] same_set_other_process=[dict get $counts OTHER_PROCESS]"
    puts "V INPUT AUDIT: candidates=[dict get $input_counts V_INPUT_CANDIDATE] other_temperature=[dict get $input_counts OTHER_TEMPERATURE] excluded_target=[dict get $input_counts EXCLUDED_TARGET_POINT] nearest_candidates=[dict get $input_counts NEAREST_DB_CANDIDATE] fixed_restore=[dict get $input_counts FIXED_RESTORE_DB]"
    puts "QUERY SCOPE: library metadata only; fixed-path membership and SCALING_POWER_NET eligibility are NOT checked."
    if {$verbose} {
        set number 0
        foreach row $rows {
            incr number
            lassign [catalog_row_reason $row $set_name $cfg] lookup input
            puts "AUDIT LIB $number: lookup=$lookup v_input=$input process=[dict get $row process] voltage=[dict get $row v] V temperature=[dict get $row t] C"
            puts "  LIB=[dict get $row lib_name]"
            puts "  SET=[dict get $row family]"
            puts "  DB=[dict get $row file]"
        }
    }
    foreach section [list [list UNPARSED $ignored] [list NOT_CATALOGED $skipped]] {
        lassign $section label items
        set limit [expr {$verbose ? [llength $items] : 3}]
        foreach row [lrange $items 0 [expr {$limit-1}]] {
            puts "$label: LIB=[dict get $row lib_name] reason=[dict get $row reason]"
            puts "  DB=[dict get $row path]"
        }
        if {[llength $items] > $limit} {
            puts "$label: remaining=[expr {[llength $items]-$limit}] (set SHOW_ALL_LOADED_LIBRARIES 1 for all entries)"
        }
    }
    if {!$verbose} {
        puts "DETAIL OPTION: set SHOW_ALL_LOADED_LIBRARIES 1 at the top of this query Tcl to print every loaded-library decision."
    }
}

proc library_scaling_group_report::failed_set_name {} {
    if {![info exists ::scaling_config] || ![dict exists $::scaling_config out_rpt]} {
        error "Set LIBRARY_NAME, or use this query in the SAME pt_shell with the original scaling_config from the failed run."
    }
    set requested [file normalize [dict get $::scaling_config out_rpt]]
    set out [file join [file dirname $requested] "restored_[file tail $requested]"]
    set candidates [list [file join [file dirname $out] details "[file tail $out].log"] ${out}.log]
    set log_file ""
    foreach candidate $candidates {
        if {![file isfile $candidate] || ![file readable $candidate]} { continue }
        if {$log_file eq "" || [file mtime $candidate] > [file mtime $log_file]} {
            set log_file $candidate
        }
    }
    if {$log_file eq ""} {
        error "LG-001: No readable log for the current scaling_config. Set LIBRARY_NAME manually. Expected: $candidates"
    }
    set fp [open $log_file r]
    # Match ASCII log structure; do not depend on the company terminal encoding.
    fconfigure $fp -encoding iso8859-1
    set last_error ""
    while {[gets $fp line] >= 0} {
        if {[string match {RUN ERROR:*} $line]} { set last_error $line }
    }
    close $fp
    if {![regexp {^RUN ERROR: Cannot build scaling inputs for required library set '([^']+)':} $last_error -> set_name]} {
        error "LG-001: The latest RUN ERROR is not a library-set planning error. Set LIBRARY_NAME manually. Log: $log_file"
    }
    puts "AUTO-SELECTED FAILED LIBRARY SET: $set_name"
    puts "AUTO-SELECT SOURCE: $log_file"
    return $set_name
}

# Reproduce only the 1D V range check, including target-temperature filtering
# and exact target-point exclusion. This does not prove native group coverage.
proc library_scaling_group_report::show_voltage_range {members cfg} {
    if {![dict exists $cfg target_v] || ![dict exists $cfg target_t] ||
        [string toupper [dict get $cfg mode]] ne "V"} { return }
    set target [dict get $cfg target_v]
    set temperature [dict get $cfg target_t]
    set loaded {}
    set eligible {}
    foreach row $members {
        if {abs([dict get $row t] - $temperature) >= 1e-8} { continue }
        set v [dict get $row v]
        lappend loaded $v
        if {abs($v - $target) >= 1e-8} { lappend eligible $v }
    }
    set loaded [lsort -real -unique $loaded]
    set eligible [lsort -real -unique $eligible]
    set lower NONE
    set upper NONE
    foreach v $eligible {
        if {$v < $target} { set lower $v }
        if {$v > $target && $upper eq "NONE"} { set upper $v }
    }
    set status BRACKET_AVAILABLE
    if {[llength $loaded] <= 1} {
        set status STATIC_ON_V_AXIS
    } elseif {$lower eq "NONE" || $upper eq "NONE"} {
        set status CANNOT_BRACKET
    }
    if {[dict exists $cfg fixed_library_set] &&
        [llength [info commands ::auto_scaling::resolve_fixed_families]]} {
        set selected [::auto_scaling::resolve_fixed_families \
            [dict get $cfg fixed_library_set] [dict get $cfg catalog_families] 0]
        if {[lsearch -exact $selected [dict get [lindex $members 0] family]] >= 0} {
            set status EXPLICIT_FIXED_SET
            if {[dict exists $cfg fixed_library_voltage] &&
                [string equal -nocase [dict get $cfg fixed_library_voltage] nearest]} {
                set status NEAREST_DB_POLICY
            }
        }
    } elseif {[dict exists $cfg fixed_library_set] &&
        [string equal -nocase [dict get $cfg fixed_library_set] [dict get [lindex $members 0] family]]} {
        set status EXPLICIT_FIXED_SET
    }
    puts "V CHECK: target=$target temperature=$temperature loaded_at_target_temperature=$loaded"
    puts "V CHECK: after_target_exclusion=$eligible lower=$lower upper=$upper status=$status"
    if {$status eq "NEAREST_DB_POLICY"} {
        set family [dict get [lindex $members 0] family]
        set process [dict get [lindex $members 0] process]
        if {[catch {set chosen [::auto_scaling::nearest_library_row $members $process $family $target $temperature]} reason]} {
            puts "NEAREST DB CANDIDATE: UNAVAILABLE | $reason"
        } else {
            puts "NEAREST DB CANDIDATE: voltage=[dict get $chosen v] V LIB=[dict get $chosen lib_name] DB=[dict get $chosen file]"
        }
        puts "NOTE: nearest selection includes exact target points; candidate lookup does not prove instance binding or target-rail scope."
    }
    puts "NOTE: V CHECK uses catalog values and planner rules, not effective PG-pin voltages or a full scaling validation."
}

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
    set matching_processes {}
    set catalog_families {}
    foreach row [dict get $catalog rows] {
        if {$process eq "" || [dict get $row process] eq $process} {
            lappend catalog_families [dict get $row family]
        }
        if {![string equal -nocase [dict get $row family] $set_name]} { continue }
        lappend matching_processes [dict get $row process]
        if {$process ne "" && [dict get $row process] ne $process} { continue }
        lappend members $row
    }
    dict set cfg catalog_families [lsort -unique $catalog_families]
    show_catalog_audit $catalog $set_name $cfg
    if {![llength $members]} {
        puts "SET LOOKUP: process_filter=$process name_matches_in_processes=[lsort -unique $matching_processes]"
        error "No exact loaded library or scaling-script library set named '$set_name'; found 0 (process filter='$process'). Copy only the name inside the quotes after library set, without quotes or the rest of the error message."
    }
    puts "SELECTED LIBRARY SET: [dict get [lindex $members 0] family]"
    puts "LOADED SET MEMBERS: [llength $members] | process_filter=$process"
    if {[dict exists $cfg target_v] && [dict exists $cfg target_t]} {
        puts "SCALING RUN TARGET: voltage=[dict get $cfg target_v] V temperature=[dict get $cfg target_t] C axis=[dict get $cfg mode]"
    }
    show_voltage_range $members $cfg
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
    set automatic [expr {$library_name eq ""}]
    if {$library_name eq ""} {
        set library_name [failed_set_name]
    }
    foreach command {get_libs sizeof_collection foreach_in_collection get_object_name get_attribute report_lib_groups redirect} {
        if {![llength [info commands $command]]} {
            error "PrimeTime command '$command' is missing. Source this file in pt_shell after restore_session."
        }
    }
    if {$automatic} {
        show_library_set $library_name
        return
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
