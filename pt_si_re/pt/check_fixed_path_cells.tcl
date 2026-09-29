# Diagnose FP-002 in the SAME pt_shell where the scaling run failed.
# Usage: source /absolute/path/to/pt/check_fixed_path_cells.tcl
# No settings: reads fixed_tcl/delay_type from the original scaling_config.
# Reports counts and original path indices; no instance names are printed.
# Shows the actual file/design so you can compare with a working corner.
# Temporarily queries from the top level, then restores the current instance.
# No V/T, library-group, timing, file, or fixed-path changes are performed.
# This checks cell-name matching, not timing-path existence or PG connectivity.
# ASCII source/output avoids UTF-8/EUC-KR source-encoding problems.

namespace eval fixed_path_cell_check {}

proc fixed_path_cell_check::inspect {fixed} {
    set paths [dict get $fixed paths]
    set indices [::auto_scaling::fixed_path_indices $paths]
    set origins [dict create]
    set path_cells {}
    set invalid {}
    foreach item $paths idx $indices {
        lassign $item key from to through edges
        set cells {}
        set bad_format 0
        foreach pin [concat [list $from] $through [list $to]] {
            set slash [string last / $pin]
            if {$slash <= 0} { set bad_format 1; continue }
            set cell [string range $pin 0 [expr {$slash-1}]]
            lappend cells $cell
            if {![dict exists $origins $cell]} {
                dict set origins $cell [dict create pin $pin idx $idx]
            }
        }
        lappend path_cells [lsort -unique $cells]
        lappend invalid $bad_format
    }
    set names [lsort [dict keys $origins]]
    set canonical [dict create]
    # Batch common exact names; inspect individual names only if unmatched.
    for {set offset 0} {$offset < [llength $names]} {incr offset 512} {
        set found [get_cells -quiet -exact [lrange $names $offset [expr {$offset+511}]]]
        foreach name [get_object_name $found] { dict set canonical $name 1 }
    }
    set counts [dict create]
    set matched 0
    set missing 0
    set ambiguous 0
    set samples {}
    foreach name $names {
        if {[dict exists $canonical $name]} {
            set count 1
        } else {
            set cells [get_cells -quiet -exact [list $name]]
            set count [sizeof_collection $cells]
            if {$count == 1} { dict set canonical [get_object_name $cells] 1 }
        }
        dict set counts $name $count
        if {$count == 1} { incr matched } elseif {$count == 0} { incr missing } else { incr ambiguous }
        if {$count != 1 && [llength $samples] < 3} {
            set origin [dict get $origins $name]
            set pins [get_pins -quiet -exact [list [dict get $origin pin]]]
            set pin_count [sizeof_collection $pins]
            set owner_count 0
            if {$pin_count == 1} {
                set owner_count [sizeof_collection [get_cells -quiet -of_objects $pins]]
            }
            lappend samples [dict create idx [dict get $origin idx] cell_matches $count \
                pin_matches $pin_count pin_owner_cells $owner_count]
        }
    }
    set affected {}
    set format_errors 0
    foreach cells $path_cells bad_format $invalid idx $indices {
        if {$bad_format} { incr format_errors }
        set bad $bad_format
        foreach name $cells {
            if {[dict get $counts $name] != 1} { set bad 1; break }
        }
        if {$bad} { lappend affected $idx }
    }
    set status ALL_CELLS_MATCH
    if {$missing} { set status PARTIAL_MATCH }
    if {$matched == 0 && [llength $names]} { set status NONE_MATCH }
    if {$ambiguous} { set status AMBIGUOUS }
    if {$format_errors} { set status INVALID_PIN_FORMAT }
    if {$status eq "ALL_CELLS_MATCH" && [dict size $canonical] < [llength $names]} {
        set status CELL_ALIAS_COLLISION
    }
    set total [llength $paths]
    puts "FIXED CELL CHECK: status=$status"
    puts "COUNTS: paths=$total affected_paths=[llength $affected] cells=[llength $names] matched=$matched missing=$missing ambiguous=$ambiguous invalid_format_paths=$format_errors"
    puts "ORIGINAL INDICES: affected_first_10=[lrange $affected 0 9]"
    foreach sample $samples {
        puts "SAMPLE: idx=[dict get $sample idx] cell_matches=[dict get $sample cell_matches] pin_matches=[dict get $sample pin_matches] pin_owner_cells=[dict get $sample pin_owner_cells]"
    }
    puts "NOTE: no paths were skipped, renamed, or renumbered. A matched cell does not prove a valid timing path."
    return [dict create status $status paths $total affected_paths [llength $affected] \
        cells [llength $names] matched $matched missing $missing ambiguous $ambiguous \
        invalid_format_paths $format_errors affected_indices $affected samples $samples]
}

proc fixed_path_cell_check::run {} {
    foreach command {get_cells get_pins sizeof_collection get_object_name foreach_in_collection current_design current_instance} {
        if {![llength [info commands ::$command]]} {
            error "PrimeTime command '$command' is missing. Use pt_shell after restore_session."
        }
    }
    if {![info exists ::scaling_config] ||
        ![dict exists $::scaling_config fixed_tcl] ||
        ![llength [info commands ::auto_scaling::read_fixed]]} {
        error "Use this query in the SAME pt_shell where run_scaling_after_restore.tcl failed; the original scaling_config and read_fixed procedure are required."
    }
    set dtype max
    if {[dict exists $::scaling_config delay_type]} { set dtype [dict get $::scaling_config delay_type] }
    set fixed [::auto_scaling::read_fixed [dict get $::scaling_config fixed_tcl] $dtype]
    set original_scope [current_instance .]
    puts "SOURCE: fixed_file=[dict get $fixed file] delay_type=$dtype"
    puts "CONTEXT: current_design=[get_object_name [current_design]] original_scope=$original_scope query_scope=TOP"
    set fixed_enabled 0
    set fixed_voltage UNUSED
    if {[dict exists $::scaling_config fixed_library_set] &&
        [string trim [dict get $::scaling_config fixed_library_set]] ne ""} {
        set fixed_enabled 1
        if {[dict exists $::scaling_config fixed_library_voltage]} {
            set fixed_voltage [dict get $::scaling_config fixed_library_voltage]
        }
    }
    puts "FIXED SET OPTION: enabled=$fixed_enabled expected_db_voltage=$fixed_voltage"
    set code [catch {
        current_instance
        inspect $fixed
    } result options]
    if {$original_scope eq ""} { current_instance } else { current_instance $original_scope }
    if {$code} { return -options $options $result }
    return $result
}

fixed_path_cell_check::run
