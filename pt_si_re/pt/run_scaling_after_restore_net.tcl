# PrimeTime restore_session scaling in NET MODE.
#
# Usage:
#   pt_shell
#   restore_session /path/to/saved_session
#   edit USER SETTINGS below
#   source /path/to/pt_si_re/pt/run_scaling_after_restore_net.tcl
#
# Path mode (run_scaling_after_restore.tcl) applies TARGET_VOLTAGE only to the
# fixed-path cells, one PG pin at a time. Clock-tree cells, off-path cells and
# SI aggressors then stay at the restored voltage, which adds clock-skew and
# crosstalk error.
#
# Net mode applies TARGET_VOLTAGE ONCE to every net in SCALING_POWER_NET (and
# the UPF segments connected to it), so every cell powered by that net is
# analyzed at the target voltage, like the ground-truth session. Before any
# voltage change the script proves from the session what the net feeds:
#   NET_SCOPE_AUDIT  every leaf cell with a primary_power PG pin on the net,
#                    counted per net and per linked library
#                    (details/<report>.net_scope.txt)
#   NET-001          every such library must have an active lib_scaling_group
# After the change it proves that the net and every PG pin on it report the
# target voltage (NET-002/NET-003, details/<report>.net_power.txt).
#
# This file sources run_scaling_after_restore.tcl in load-only mode and reuses
# its procedures (LOO guards TL-001/TL-003, planning, reports, .dcalc checks).
# Fixes to that file are inherited. Results use a "_net" report name, so
# path-mode results are never overwritten.
#
# Net mode supports SCALING_AXIS V only, no FIXED_LIBRARY_SET, and a u_mem
# VDDPE target equal to TARGET_VOLTAGE (VDDPE sits on the scaled net).

# ======================= USER SETTINGS ========================
set TARGET_PROCESS      "SSPG"
set TARGET_VOLTAGE      0.75
set TARGET_TEMPERATURE  25
set TARGET_BEOL         "rcmax"
set SCALING_AXIS        "V"       ;# net mode: V only
set ANALYSIS            "setup"   ;# setup or hold

set FIXED_PATH_FILE "fixed_paths.tcl"
set RESULT_FOLDER   "auto_scaling_output"

# Progress print interval (minutes) for long phases. No effect on results.
set PROGRESS_INTERVAL_MINUTES 10

# Supply net(s) that receive TARGET_VOLTAGE. Separate several nets with spaces
# or commas (for example "VDD VDD_CPU"); all of them get the same voltage.
# In net mode the WHOLE net is set (clock tree, off-path cells, aggressors).
# Every other supply net stays at its restored voltage. Check the
# AUTO-FIXED POWER NETS line in the log for a net that was left out.
set SCALING_POWER_NET "" ;# target-voltage rail(s)

# VDDPE is the u_mem Liberty/cell PG pin name, not a supply net name.
# Cell or linked-library name patterns of fixed-path macros whose native
# multirail scaling group is checked. * and ? allowed; separate with commas.
# Empty disables the u_mem checks.
set VDDPE_SCALING_NAME_PATTERNS "*u_mem*"
# Net mode: leave empty or set equal to TARGET_VOLTAGE. The u_mem VDDPE pin
# must sit on a net in SCALING_POWER_NET and follows that net's voltage.
set TARGET_VDDPE_VOLTAGE ""

# Net mode: must stay empty (fixed-set and nearest policies are path-mode only).
set FIXED_LIBRARY_SET     ""
set FIXED_LIBRARY_VOLTAGE "restore"
# ===================== END USER SETTINGS ======================

namespace eval auto_scaling_net {
    variable setting_names {
        TARGET_PROCESS TARGET_VOLTAGE TARGET_TEMPERATURE TARGET_BEOL SCALING_AXIS
        ANALYSIS FIXED_PATH_FILE RESULT_FOLDER PROGRESS_INTERVAL_MINUTES
        SCALING_POWER_NET VDDPE_SCALING_NAME_PATTERNS TARGET_VDDPE_VOLTAGE
        FIXED_LIBRARY_SET FIXED_LIBRARY_VOLTAGE
    }
    variable script_dir [file dirname [file normalize [info script]]]
    # Sidecars that only this script writes. The original reset_output_files
    # does not know them, so they are cleared here on every rerun.
    variable net_sidecars {.net_scope.txt .net_power.txt .clock.dcalc}
    # NET-003 sample size (other net cells beside the fixed-path cells).
    variable sample_other_cells 200
    variable sample_clock_cells 100
    variable sample_control_cells 20
}

# Source the original in load-only mode at global scope (its USER SETTINGS
# block must set globals), then put back THIS file's settings and the prior
# state of the load-only flag.
proc auto_scaling_net::load_original {} {
    variable setting_names
    variable script_dir
    set saved [dict create]
    foreach name $setting_names {
        if {[info exists ::$name]} { dict set saved $name [set ::$name] }
    }
    set had_flag [info exists ::auto_scaling_restored_load_only]
    if {$had_flag} { set old_flag $::auto_scaling_restored_load_only }
    set ::auto_scaling_restored_load_only 1
    set code [catch {
        uplevel #0 [list source [file join $script_dir run_scaling_after_restore.tcl]]
    } result options]
    if {$had_flag} {
        set ::auto_scaling_restored_load_only $old_flag
    } else {
        unset -nocomplain ::auto_scaling_restored_load_only
    }
    foreach name $setting_names {
        if {[dict exists $saved $name]} {
            set ::$name [dict get $saved $name]
        } else {
            unset -nocomplain ::$name
        }
    }
    if {$code} { return -options $options $result }
    return
}
auto_scaling_net::load_original

# ---------------------------------------------------------------------------
# Configuration (checked before the session is touched)
# ---------------------------------------------------------------------------

proc auto_scaling_net::net_report_name {path} {
    set tail [file tail $path]
    if {[string match "*_net.rpt" $tail]} { return $path }
    return [file join [file dirname $path] "[file rootname $tail]_net.rpt"]
}

proc auto_scaling_net::check_config {cfg} {
    if {[string trim [auto_scaling::option $cfg fixed_library_set ""]] ne ""} {
        error "NET-010: FIXED_LIBRARY_SET must be empty in net mode (fixed-set and nearest policies are not supported). Clear it, or use run_scaling_after_restore.tcl (path mode) for that policy."
    }
    set mode [string toupper [auto_scaling::option $cfg mode ""]]
    if {$mode ne "V"} {
        error "NET-011: SCALING_AXIS must be V in net mode (got '$mode'). Net mode changes voltage only; use run_scaling_after_restore.tcl for T or VT."
    }
    set target_v [auto_scaling::number [auto_scaling::need $cfg target_v]]
    set vddpe [string trim [auto_scaling::option $cfg target_vddpe ""]]
    if {$vddpe ne ""} {
        if {[catch {auto_scaling::number $vddpe} vddpe_value]} {
            error "NET-012: TARGET_VDDPE_VOLTAGE is not a number: '$vddpe'. Leave it empty or set it to TARGET_VOLTAGE."
        }
        if {![auto_scaling::same $vddpe_value $target_v]} {
            error "NET-012: TARGET_VDDPE_VOLTAGE ($vddpe_value V) must be empty or equal to TARGET_VOLTAGE ($target_v V) in net mode. u_mem VDDPE sits on the core net and one net carries one voltage. Use run_scaling_after_restore.tcl for a different VDDPE target."
        }
    }
    set nets [auto_scaling::need $cfg scaling_power_nets]
    foreach name $nets {
        if {[regexp {[[:space:],]} $name]} {
            error "NET-013: SCALING_POWER_NET was not split into net names ('$name'). run_scaling_after_restore.tcl is older than this file; update both files together."
        }
    }
    if {![llength $nets]} { error "NET-013: SCALING_POWER_NET is empty." }
    return $cfg
}

proc auto_scaling_net::build_config {} {
    set cfg [auto_scaling::build_restore_config]
    check_config $cfg
    dict set cfg out_rpt [net_report_name [dict get $cfg out_rpt]]
    return $cfg
}

proc auto_scaling_net::actual_report {cfg} {
    set requested [file normalize [net_report_name [dict get $cfg out_rpt]]]
    return [file join [file dirname $requested] "restored_[file tail $requested]"]
}

# Clear this run's own sidecars (details/ and legacy adjacent names).
proc auto_scaling_net::reset_net_sidecars {out} {
    variable net_sidecars
    set previous {}
    foreach suffix $net_sidecars {
        foreach path [list [auto_scaling::detail_path $out $suffix] ${out}${suffix}] {
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

# ---------------------------------------------------------------------------
# Scaling nets and their UPF segments
# ---------------------------------------------------------------------------

# Every listed net resolved by resolve_configured_supply_roles (full_name)
# plus the UPF segments connected to it. set_voltage on a net also sets its
# connected segments, so those segments are scaling rails too, even though
# the path-mode role map calls them auto-fixed.
proc auto_scaling_net::resolve_scaling_nets {roles} {
    set objects [dict create]
    foreach_in_collection supply [get_supply_nets -quiet -hierarchy *] {
        set full_name [get_attribute $supply full_name]
        if {![dict exists $objects $full_name]} { dict set objects $full_name $supply }
    }
    set listed {}
    dict for {name role} $roles {
        if {$role eq "scaling"} { lappend listed $name }
    }
    if {![llength $listed]} { error "NET-004: No scaling power net was resolved in the restored session." }
    set segments [dict create]
    set owner [dict create]
    set shared {}
    foreach name $listed {
        if {![dict exists $objects $name]} {
            error "NET-004: Resolved scaling net '$name' has no supply net object."
        }
        set segs [list $name]
        set found [get_supply_nets -quiet -segments [dict get $objects $name]]
        foreach_in_collection seg $found {
            set seg_name [get_attribute $seg full_name]
            if {[lsearch -exact $segs $seg_name] < 0} { lappend segs $seg_name }
            if {![dict exists $objects $seg_name]} { dict set objects $seg_name $seg }
        }
        foreach seg_name $segs {
            if {[dict exists $owner $seg_name] && [dict get $owner $seg_name] ne $name} {
                lappend shared "$seg_name ([dict get $owner $seg_name], $name)"
            } else {
                dict set owner $seg_name $name
            }
        }
        dict set segments $name $segs
    }
    set all_segments {}
    dict for {name segs} $segments {
        foreach seg $segs { if {[lsearch -exact $all_segments $seg] < 0} { lappend all_segments $seg } }
    }
    set seg_objects [dict create]
    foreach seg $all_segments { dict set seg_objects $seg [dict get $objects $seg] }
    set fixed {}
    dict for {name role} $roles {
        if {[lsearch -exact $all_segments $name] < 0} { lappend fixed $name }
    }
    foreach name $listed {
        set extra [lrange [dict get $segments $name] 1 end]
        puts "NET SEGMENTS: net=$name segments=[llength [dict get $segments $name]] connected=[expr {[llength $extra] ? $extra : "none"}]"
    }
    if {[llength $shared]} {
        puts "WARNING: Listed scaling nets share UPF segments (same electrical net listed twice): $shared"
    }
    return [dict create listed $listed segments $segments all_segments $all_segments \
        seg_objects $seg_objects fixed_nets [lsort $fixed] net_objects $objects]
}

# Segments of a listed net are scaling rails, never auto-fixed.
proc auto_scaling_net::apply_segment_roles {roles nets} {
    foreach seg [dict get $nets all_segments] {
        if {[dict exists $roles $seg] && [dict get $roles $seg] eq "scaling"} { continue }
        if {[dict exists $roles $seg]} {
            puts "NET SEGMENT RECLASSIFIED: $seg auto-fixed -> scaling (UPF segment of a listed net)"
        }
        dict set roles $seg scaling
    }
    return $roles
}

proc auto_scaling_net::supply_filter {names {negate 0}} {
    set terms {}
    set op [expr {$negate ? "!=" : "=="}]
    foreach name $names { lappend terms "supply_connection $op \"$name\"" }
    return [join $terms [expr {$negate ? " && " : " || "}]]
}

# Union that accepts empty collections on either side.
proc auto_scaling_net::union {a b} {
    if {![sizeof_collection $b]} { return $a }
    if {![sizeof_collection $a]} { return $b }
    return [add_to_collection -unique $a $b]
}

proc auto_scaling_net::pin_cell_names {pins} {
    if {![sizeof_collection $pins]} { return {} }
    set cells [dict create]
    foreach full [get_object_name $pins] pin [get_attribute -quiet $pins pin_name] {
        set suffix "/$pin"
        if {$pin eq "" || ![string match "*$suffix" $full]} {
            error "Cannot extract a cell name from PG pin full_name: $full"
        }
        dict set cells [string range $full 0 end-[string length $suffix]] 1
    }
    return [dict keys $cells]
}

# ---------------------------------------------------------------------------
# NET_SCOPE_AUDIT (read-only)
# ---------------------------------------------------------------------------

# One segment. Uses collection queries only; a per-pin loop runs only when
# the supply_connection strings do not name the segment (fallback).
proc auto_scaling_net::segment_scope {seg seg_obj} {
    set touching [get_cells -quiet -of_objects $seg_obj]
    set touching [filter_collection $touching {is_hierarchical == false}]
    set result [dict create cells $touching primary_pins "" nonprimary_only {} fallback 0]
    if {![sizeof_collection $touching]} { return $result }
    set pg [get_pg_pins -of_objects $touching]
    set on_seg [filter_collection $pg [supply_filter [list $seg]]]
    if {![sizeof_collection $on_seg]} {
        return [segment_scope_fallback $seg $touching $pg]
    }
    set primary [filter_collection $on_seg {type == primary_power}]
    set nonprimary [filter_collection $on_seg {type != primary_power}]
    dict set result primary_pins $primary
    if {![sizeof_collection $primary]} {
        # No primary_power pin at all (for example a ground net): empty scope.
        dict set result cells ""
        return $result
    }
    if {![sizeof_collection $nonprimary]} { return $result }
    # Keep a cell only if it also has a primary_power pin on this segment.
    set candidates [pin_cell_names $nonprimary]
    set candidate_cells [get_cells -quiet -exact $candidates]
    set candidate_primary [filter_collection [get_pg_pins -of_objects $candidate_cells] \
        "type == primary_power && ([supply_filter [list $seg]])"]
    set keep [dict create]
    foreach name [pin_cell_names $candidate_primary] { dict set keep $name 1 }
    set only {}
    foreach name $candidates {
        if {![dict exists $keep $name]} { lappend only $name }
    }
    if {[llength $only]} {
        set only_types [dict create]
        foreach full [get_object_name $nonprimary] type [get_attribute -quiet $nonprimary type] {
            foreach name $only {
                if {[string first "$name/" $full] == 0} { dict lappend only_types $name "$full:$type" }
            }
        }
        dict set result nonprimary_only $only_types
        dict set result cells [remove_from_collection $touching [get_cells -quiet -exact $only]]
    }
    return $result
}

proc auto_scaling_net::segment_scope_fallback {seg touching pg} {
    set total [sizeof_collection $pg]
    puts "NET SCOPE FALLBACK: supply_connection does not name segment $seg; checking $total PG pins one by one."
    set primary_cells [dict create]
    set other_cells [dict create]
    set primary_pins {}
    set done 0
    set started [clock milliseconds]
    foreach_in_collection pin $pg {
        incr done
        if {$done % 100000 == 0} {
            puts [format "NET SCOPE PROGRESS: segment=%s pins=%d/%d | %.2f min" $seg $done $total \
                [expr {([clock milliseconds] - $started) / 60000.0}]]
            flush stdout
        }
        set net [get_supply_nets -quiet -of_objects $pin]
        if {[sizeof_collection $net] != 1 || [get_attribute $net full_name] ne $seg} { continue }
        set full [get_attribute $pin full_name]
        set pin_name [get_attribute $pin pin_name]
        set cell [string range $full 0 end-[expr {[string length $pin_name] + 1}]]
        if {[get_attribute $pin type] eq "primary_power"} {
            dict set primary_cells $cell 1
            append_to_collection primary_pins $pin
        } else {
            dict lappend other_cells $cell "$full:[get_attribute $pin type]"
        }
    }
    set only [dict create]
    dict for {cell pins} $other_cells {
        if {![dict exists $primary_cells $cell]} { dict set only $cell $pins }
    }
    set cells $touching
    if {[dict size $only]} {
        set cells [remove_from_collection $touching [get_cells -quiet -exact [dict keys $only]]]
    }
    return [dict create cells $cells primary_pins $primary_pins nonprimary_only $only fallback 1]
}

proc auto_scaling_net::net_scope_audit {nets supply native_umem out} {
    set started [clock milliseconds]
    set all_cells ""
    set primary_pins ""
    set per_net [dict create]
    set per_segment [dict create]
    set nonprimary_only [dict create]
    set fallback {}
    foreach listed [dict get $nets listed] {
        set net_cells ""
        foreach seg [dict get $nets segments $listed] {
            if {![dict exists $per_segment $seg]} {
                set part [segment_scope $seg [dict get $nets seg_objects $seg]]
                dict set per_segment $seg [dict create cells [dict get $part cells] \
                    count [sizeof_collection [dict get $part cells]]]
                set primary_pins [union $primary_pins [dict get $part primary_pins]]
                dict for {cell pins} [dict get $part nonprimary_only] {
                    dict set nonprimary_only $cell [list $seg $pins]
                }
                if {[dict get $part fallback]} { lappend fallback $seg }
            }
            set net_cells [union $net_cells [dict get $per_segment $seg cells]]
        }
        dict set per_net $listed [sizeof_collection $net_cells]
        set all_cells [union $all_cells $net_cells]
        if {![sizeof_collection $net_cells]} {
            error "NET-004: Scaling net '$listed' feeds no leaf cell through a primary_power PG pin (a ground net, an unused net, or a wrong name). Nothing was changed. Check SCALING_POWER_NET against RESTORED SUPPLY NETS."
        }
    }
    set total [sizeof_collection $all_cells]

    # Cells that also draw primary power from a net outside the scaling set.
    # Object difference, so it also holds when the fallback resolved names.
    set mixed [filter_collection [get_pg_pins -of_objects $all_cells] {type == primary_power}]
    if {[sizeof_collection $mixed] && [sizeof_collection $primary_pins]} {
        set mixed [remove_from_collection $mixed $primary_pins]
    }
    set mixed_rows {}
    if {[sizeof_collection $mixed]} {
        foreach full [get_object_name $mixed] conn [get_attribute -quiet $mixed supply_connection] {
            lappend mixed_rows "$full:[expr {$conn eq "" ? "<unconnected>" : $conn}]"
        }
    }

    # Per linked library: name + normalized source DB.
    set libraries {}
    set used_libs [get_libs -quiet -of_objects [get_lib_cells -quiet -of_objects $all_cells]]
    foreach_in_collection lib $used_libs {
        set name [get_attribute $lib full_name]
        set db [get_attribute -quiet $lib source_file_name]
        if {$db ne ""} { set db [file normalize $db] }
        set instances [get_cells -quiet -of_objects [get_lib_cells -quiet -of_objects $lib]]
        set count [sizeof_collection [remove_from_collection -intersect $all_cells $instances]]
        set group [get_attribute -quiet $lib lib_scaling_group]
        set status [expr {($group ne "" && [sizeof_collection $group]) ? "ACTIVE" : "NONE_YET"}]
        lappend libraries [dict create name $name db $db cells $count group_before $status]
    }
    set libraries [lsort -command auto_scaling_net::compare_library_cells $libraries]

    # Existing PG-pin overrides (cell-level set_voltage wins over the net).
    set overrides ""
    if {[catch {filter_collection $primary_pins {voltage_source != CONNECTED_SUPPLY_NET}} overrides]} {
        set overrides ""
    }

    set path_cells [dict get $supply path_cells]
    set path_on_net [sizeof_collection [remove_from_collection -intersect $path_cells $all_cells]]

    # A selected u_mem macro must have VDDPE on a scaling net segment, because
    # net mode never sets VDDPE separately.
    set umem_rows {}
    foreach name [dict get $native_umem cell_names] {
        set cell [get_cells -quiet -exact $name]
        set vddpe_net ""
        foreach_in_collection pin [get_pg_pins -of_objects $cell] {
            if {![string equal -nocase [get_attribute $pin pin_name] VDDPE]} { continue }
            set sn [get_supply_nets -quiet -of_objects $pin]
            if {[sizeof_collection $sn] == 1} {
                set vddpe_net [get_attribute $sn full_name]
            } else {
                set vddpe_net [get_attribute $pin supply_connection]
            }
        }
        lappend umem_rows [list $name $vddpe_net]
        if {[lsearch -exact [dict get $nets all_segments] $vddpe_net] < 0} {
            error "NET-005: u_mem cell $name has VDDPE on '$vddpe_net', not on a scaling net ([join [dict get $nets listed] ,]). Net mode cannot set VDDPE separately. Add that net to SCALING_POWER_NET if it must scale, or use run_scaling_after_restore.tcl (path mode)."
        }
    }

    set lines {}
    lappend lines "NET_SCOPE_AUDIT mode=net read_only=yes"
    lappend lines "LISTED_NETS: [join [dict get $nets listed] ,]"
    foreach listed [dict get $nets listed] {
        lappend lines "NET $listed cells=[dict get $per_net $listed] segments=[join [dict get $nets segments $listed] ,]"
        foreach seg [dict get $nets segments $listed] {
            lappend lines "  SEGMENT $seg cells=[dict get $per_segment $seg count]"
        }
    }
    lappend lines "AUTO_FIXED_NETS: [join [dict get $nets fixed_nets] ,]"
    lappend lines "TOTAL net_cells=$total libraries=[llength $libraries] primary_pins=[sizeof_collection $primary_pins] nonprimary_only_cells=[dict size $nonprimary_only] mixed_rail_pins=[sizeof_collection $mixed] fallback_segments=[llength $fallback]"
    lappend lines "FIXED_PATH_CELLS_ON_NET: $path_on_net of [sizeof_collection $path_cells]"
    lappend lines "PG_PIN_OVERRIDES_BEFORE: [sizeof_collection $overrides] (cell-level voltage wins over the net; NET-003 fails if not at target after the change)"
    foreach record $libraries {
        lappend lines "LIBRARY lib=[dict get $record name] cells=[dict get $record cells] group_before=[dict get $record group_before] DB=[dict get $record db]"
    }
    set shown 0
    dict for {cell record} $nonprimary_only {
        if {[incr shown] > 50} { lappend lines "NONPRIMARY_ONLY ... ([dict size $nonprimary_only] total)"; break }
        lappend lines "NONPRIMARY_ONLY cell=$cell segment=[lindex $record 0] pins=[join [lindex $record 1] ,] (not in scope; informational)"
    }
    foreach row [lrange $mixed_rows 0 49] { lappend lines "MIXED_RAIL_PIN $row (cell in scope; this pin keeps its own net voltage)" }
    if {[llength $mixed_rows] > 50} { lappend lines "MIXED_RAIL_PIN ... ([llength $mixed_rows] total)" }
    foreach row [lrange [get_object_name $overrides] 0 49] { lappend lines "PG_PIN_OVERRIDE $row" }
    foreach row $umem_rows { lappend lines "U_MEM_VDDPE cell=[lindex $row 0] net=[lindex $row 1]" }
    if {[llength $fallback]} { lappend lines "FALLBACK_SEGMENTS: $fallback" }
    lappend lines [format "NET_SCOPE_TIME: %.2f min" [expr {([clock milliseconds] - $started) / 60000.0}]]
    lappend lines "NET_SCOPE_STATUS: DONE"
    set path [auto_scaling::detail_path $out .net_scope.txt]
    auto_scaling::write_text $path "[join $lines \n]\n"

    puts "NET SCOPE: net=[join [dict get $nets listed] ,] cells=$total libraries=[llength $libraries]"
    foreach listed [dict get $nets listed] { puts "NET SCOPE NET: $listed cells=[dict get $per_net $listed]" }
    foreach record $libraries {
        puts "NET SCOPE LIBRARY: lib=[dict get $record name] cells=[dict get $record cells] group_before=[dict get $record group_before]"
    }
    if {[dict size $nonprimary_only]} { puts "NET SCOPE: [dict size $nonprimary_only] cell(s) touch the net only through non-primary PG pins (not in scope). See $path" }
    if {[sizeof_collection $mixed]} { puts "WARNING: [sizeof_collection $mixed] primary_power pin(s) of in-scope cells are on other nets (mixed-rail cells). See $path" }
    if {[sizeof_collection $overrides]} { puts "WARNING: [sizeof_collection $overrides] scaling-net PG pin(s) already carry a non-net voltage source. See $path" }
    puts "NET SCOPE FILE: $path"
    return [dict create cells $all_cells primary_pins $primary_pins count $total \
        per_net $per_net libraries $libraries nets $nets evidence $path]
}

proc auto_scaling_net::compare_library_cells {a b} {
    set diff [expr {[dict get $b cells] - [dict get $a cells]}]
    if {$diff != 0} { return $diff }
    return [string compare [dict get $a name] [dict get $b name]]
}

# ---------------------------------------------------------------------------
# NET-001 (after PREPARE_SCALING_GROUPS, before any voltage change)
# ---------------------------------------------------------------------------

proc auto_scaling_net::check_net_groups {scope plan out} {
    set wanted [dict create]
    foreach record [dict get $scope libraries] {
        dict set wanted [list [dict get $record db] [dict get $record name]] $record
    }
    set planned [dict create]
    foreach row [auto_scaling::option $plan scaling_library_rows {}] {
        dict set planned [list [file normalize [dict get $row file]] [dict get $row lib_name]] 1
    }
    set native [auto_scaling::option [auto_scaling::option $plan native_umem {}] library_names {}]
    set status [dict create]
    foreach_in_collection lib [get_libs -quiet *] {
        set name [get_attribute $lib full_name]
        set db [get_attribute -quiet $lib source_file_name]
        if {$db ne ""} { set db [file normalize $db] }
        set key [list $db $name]
        if {![dict exists $wanted $key]} { continue }
        set group [get_attribute -quiet $lib lib_scaling_group]
        if {$group ne "" && [sizeof_collection $group]} {
            dict set status $key ACTIVE
        } elseif {![dict exists $status $key]} {
            dict set status $key NONE
        }
    }
    set lines {}
    set missing {}
    set unplanned {}
    dict for {key record} $wanted {
        set state [lookup $status $key NOT_LOADED]
        set is_planned [expr {[dict exists $planned $key] || [lsearch -exact $native [dict get $record name]] >= 0}]
        lappend lines "NET-001 LIBRARY lib=[dict get $record name] cells=[dict get $record cells] group=$state planned_by_this_run=[expr {$is_planned ? "yes" : "no"}] DB=[dict get $record db]"
        if {$state ne "ACTIVE"} {
            lappend missing "[dict get $record name] (cells=[dict get $record cells])"
        } elseif {!$is_planned} {
            lappend unplanned [dict get $record name]
        }
    }
    set path [auto_scaling::detail_path $out .net_scope.txt]
    if {[llength $missing]} {
        lappend lines "NET-001 STATUS: FAILED"
        auto_scaling::append_text $path "[join $lines \n]\n"
        error "NET-001: [llength $missing] librar[expr {[llength $missing] == 1 ? "y" : "ies"}] used by cells on the scaling net [expr {[llength $missing] == 1 ? "has" : "have"}] no active lib_scaling_group: [join $missing {, }]. Those cells would get the target voltage with no interpolation. Nothing was changed. Put their DBs in a target-excluded scaling group (or restore a session that has one), or remove that net from SCALING_POWER_NET. Evidence: $path"
    }
    lappend lines "NET-001 STATUS: PASSED libraries=[dict size $wanted]"
    auto_scaling::append_text $path "[join $lines \n]\n"
    if {[llength $unplanned]} {
        puts "WARNING: Net libraries with a restored scaling group that this run did not plan (bracket not re-checked here; check the .dcalc evidence): $unplanned"
    }
    puts "NET CHECK NET-001: PASSED | libraries=[dict size $wanted] all have an active scaling group"
}

# ---------------------------------------------------------------------------
# APPLY and NET-002 / NET-003
# ---------------------------------------------------------------------------

# report_power_pin_info rows: cell pin type max [min] [net]
proc auto_scaling_net::power_pin_rows {report} {
    set rows {}
    foreach line [split $report "\n"] {
        set fields [regexp -all -inline {\S+} $line]
        if {[llength $fields] < 4} { continue }
        lassign $fields cell pin type max
        if {$type ni {primary_power primary_ground backup_power backup_ground internal_power internal_ground nwell pwell deepnwell deeppwell}} { continue }
        if {[catch {auto_scaling::number $max} max_value]} { continue }
        set rest [lrange $fields 4 end]
        set min_value ""
        if {[llength $rest] && ![catch {auto_scaling::number [lindex $rest 0]} parsed]} {
            set min_value $parsed
            set rest [lrange $rest 1 end]
        }
        set net [expr {[llength $rest] ? [lindex $rest 0] : ""}]
        lappend rows [dict create cell $cell pin $pin type $type max $max_value min $min_value net $net]
    }
    return $rows
}

# dict get with a default; keeps the raw report text (no expr conversion).
proc auto_scaling_net::lookup {values key default} {
    if {[dict exists $values $key]} { return [dict get $values $key] }
    return $default
}

# Pure check of the before/after evidence. Returns a list of error lines.
#   nets: dict with listed, all_segments, fixed_nets
#   bulk_bad: {pin max min source} rows from the attribute check, or "" when
#             the attribute check is unavailable (then the sample must pass)
proc auto_scaling_net::net_power_errors {nets target before_nets after_nets before_pins after_pins sample_cells control_cells bulk_bad} {
    set errors {}
    set before [auto_scaling::umem_supply_voltages $before_nets]
    set after [auto_scaling::umem_supply_voltages $after_nets]
    foreach seg [dict get $nets all_segments] {
        set is_listed [expr {[lsearch -exact [dict get $nets listed] $seg] >= 0}]
        if {![dict exists $after [list $seg exists]]} {
            if {$is_listed} { lappend errors "NET-002: Scaling net $seg is missing from report_supply_net after set_voltage" }
            continue
        }
        foreach key {{Max-delay Voltage} {Min-delay Voltage}} {
            if {![dict exists $after [list $seg $key]] ||
                [catch {auto_scaling::number [dict get $after [list $seg $key]]} value] ||
                ![auto_scaling::same $value $target]} {
                set shown [lookup $after [list $seg $key] unreported]
                lappend errors "NET-002: Scaling net $seg reports $key=$shown, expected $target"
            }
        }
    }
    foreach net [dict get $nets fixed_nets] {
        if {![dict exists $before [list $net exists]]} { continue }
        foreach key {{Max-delay Voltage} {Min-delay Voltage}} {
            set was [lookup $before [list $net $key] ""]
            set now [lookup $after [list $net $key] ""]
            if {![catch {auto_scaling::number $was} was_value] &&
                ![catch {auto_scaling::number $now} now_value]} {
                set changed [expr {![auto_scaling::same $was_value $now_value]}]
            } else {
                set changed [expr {$was ne $now}]
            }
            if {$changed} {
                lappend errors "NET-002: Auto-fixed net $net changed $key from '$was' to '$now'"
            }
        }
    }

    foreach row $bulk_bad {
        lassign $row pin max min source
        lappend errors "NET-003: PG pin $pin reports max=$max min=$min source=$source, expected $target"
    }
    set segments [dict create]
    foreach seg [dict get $nets all_segments] { dict set segments $seg 1 }
    set sample [dict create]
    foreach name $sample_cells { dict set sample $name 1 }
    set checked 0
    set seen_cells [dict create]
    foreach row [power_pin_rows $after_pins] {
        if {![dict exists $sample [dict get $row cell]]} { continue }
        if {[dict get $row type] ne "primary_power" || ![dict exists $segments [dict get $row net]]} { continue }
        incr checked
        dict set seen_cells [dict get $row cell] 1
        set ok [auto_scaling::same [dict get $row max] $target]
        if {[dict get $row min] ne "" && ![auto_scaling::same [dict get $row min] $target]} { set ok 0 }
        if {!$ok} {
            lappend errors "NET-003: [dict get $row cell]/[dict get $row pin] on [dict get $row net] reports max=[dict get $row max] min=[dict get $row min], expected $target"
        }
    }
    if {[llength $sample_cells] && !$checked} {
        lappend errors "NET-003: No scaling-net primary_power pin of the [llength $sample_cells] sample cell(s) was found in report_power_pin_info"
    }
    set unverified 0
    foreach name $sample_cells { if {![dict exists $seen_cells $name]} { incr unverified } }
    set prior [dict create]
    set controls [dict create]
    foreach name $control_cells { dict set controls $name 1 }
    foreach row [power_pin_rows $before_pins] {
        if {[dict exists $controls [dict get $row cell]]} {
            dict set prior [list [dict get $row cell] [dict get $row pin]] [list [dict get $row max] [dict get $row min]]
        }
    }
    set final [dict create]
    foreach row [power_pin_rows $after_pins] {
        if {[dict exists $controls [dict get $row cell]]} {
            dict set final [list [dict get $row cell] [dict get $row pin]] [list [dict get $row max] [dict get $row min]]
        }
    }
    dict for {key value} $prior {
        if {![dict exists $final $key] || [dict get $final $key] ne $value} {
            set now [lookup $final $key unreported]
            lappend errors "NET-003: Fixed-net control pin [join $key /] changed from {$value} to {$now}"
        }
    }
    return [dict create errors $errors sample_pins_checked $checked sample_cells_unverified $unverified control_pins [dict size $prior]]
}

# Pins on the scaling segments whose max/min voltage is not the target.
# Returns {rows} or the string UNAVAILABLE when the attributes cannot be read.
proc auto_scaling_net::bulk_pin_check {primary_pins target} {
    set lo [format %.9g [expr {$target - 1e-6}]]
    set hi [format %.9g [expr {$target + 1e-6}]]
    set expression "voltage_for_max_delay < $lo || voltage_for_max_delay > $hi || voltage_for_min_delay < $lo || voltage_for_min_delay > $hi"
    if {[catch {filter_collection $primary_pins $expression} bad]} {
        puts "WARNING: PG-pin voltage attributes are not filterable ($bad); NET-003 uses the report_power_pin_info sample only."
        return UNAVAILABLE
    }
    set rows {}
    if {[sizeof_collection $bad]} {
        foreach_in_collection pin [index_collection $bad 0 [expr {min(19, [sizeof_collection $bad]-1)}]] {
            lappend rows [list [get_attribute $pin full_name] \
                [get_attribute -quiet $pin voltage_for_max_delay] \
                [get_attribute -quiet $pin voltage_for_min_delay] \
                [get_attribute -quiet $pin voltage_source]]
        }
        if {[sizeof_collection $bad] > 20} {
            lappend rows [list "... [sizeof_collection $bad] pins total" - - -]
        }
    }
    return $rows
}

proc auto_scaling_net::first_cells {collection limit} {
    set size [sizeof_collection $collection]
    if {!$size || $limit <= 0} { return "" }
    return [index_collection $collection 0 [expr {min($limit, $size) - 1}]]
}

# Sample: every fixed-path scaled cell, then clock-network cells on the net,
# then other net cells, up to sample_other_cells beyond the fixed-path cells.
proc auto_scaling_net::power_sample {scope scaled_cells} {
    variable sample_other_cells
    variable sample_clock_cells
    variable sample_control_cells
    set scope_cells [dict get $scope cells]
    set others [remove_from_collection $scope_cells $scaled_cells]
    set clock_cells ""
    if {[llength [info commands ::get_clock_network_objects]] &&
        ![catch {get_clock_network_objects -type cell} clock_all]} {
        set clock_cells [first_cells [remove_from_collection -intersect $others $clock_all] $sample_clock_cells]
    }
    set rest $others
    if {[sizeof_collection $clock_cells]} { set rest [remove_from_collection $others $clock_cells] }
    set rest [first_cells $rest [expr {$sample_other_cells - [sizeof_collection $clock_cells]}]]
    set sample [union $scaled_cells [union $clock_cells $rest]]
    # Controls: leaf cells on auto-fixed nets only; they must not change.
    set controls ""
    set fixed_objects ""
    set objects [dict get $scope nets net_objects]
    foreach name [dict get $scope nets fixed_nets] {
        if {[dict exists $objects $name]} {
            set fixed_objects [union $fixed_objects [dict get $objects $name]]
        }
    }
    if {[sizeof_collection $fixed_objects]} {
        set fixed_cells [filter_collection [get_cells -quiet -of_objects $fixed_objects] {is_hierarchical == false}]
        set controls [first_cells [remove_from_collection $fixed_cells $scope_cells] $sample_control_cells]
    }
    return [dict create sample $sample clock_cells $clock_cells controls $controls]
}

proc auto_scaling_net::power_snapshot {cells} {
    set pins ""
    if {[sizeof_collection $cells]} {
        redirect -variable pins { report_power_pin_info $cells }
    }
    redirect -variable nets { report_supply_net }
    return [dict create pins $pins nets $nets]
}

proc auto_scaling_net::apply_net_voltage {scope scaled_cells native_umem target_v target_t out} {
    set nets [dict get $scope nets]
    set picks [power_sample $scope $scaled_cells]
    set sample [dict get $picks sample]
    set controls [dict get $picks controls]
    set snapshot_cells [union $sample $controls]
    puts "NET POWER SAMPLE: fixed_path_cells=[sizeof_collection $scaled_cells] clock_cells=[sizeof_collection [dict get $picks clock_cells]] total_sample=[sizeof_collection $sample] fixed_net_controls=[sizeof_collection $controls]"
    set before [power_snapshot $snapshot_cells]

    auto_scaling::check_status set_temperature [list set_temperature $target_t -object_list [dict get $scope cells]]
    puts "APPLY NET TEMPERATURE: target=$target_t C cells=[dict get $scope count]"
    set objects [dict get $nets net_objects]
    foreach name [dict get $nets listed] {
        puts "APPLY NET VOLTAGE: set_voltage $target_v -min $target_v -object_list $name (segments=[join [dict get $nets segments $name] ,])"
        auto_scaling::check_status "set_voltage($name)" [list set_voltage $target_v -min $target_v \
            -object_list [dict get $objects $name]]
    }
    set after [power_snapshot $snapshot_cells]

    set bulk [bulk_pin_check [dict get $scope primary_pins] $target_v]
    set bulk_rows [expr {$bulk eq "UNAVAILABLE" ? {} : $bulk}]
    set sample_names [get_object_name $sample]
    set control_names [get_object_name $controls]
    set result [net_power_errors $nets $target_v [dict get $before nets] [dict get $after nets] \
        [dict get $before pins] [dict get $after pins] $sample_names $control_names $bulk_rows]
    set errors [dict get $result errors]

    if {[llength [dict get $native_umem cell_names]]} {
        verify_umem_net_power $out $native_umem $target_v $before $after
    }

    set status [expr {[llength $errors] ? "FAILED" : "PASSED"}]
    set text "NET_POWER_VERIFICATION: $status\n"
    append text "TARGET_VOLTAGE: $target_v V (max and min)\nTARGET_TEMPERATURE: $target_t C\n"
    append text "SCALING_NETS: [join [dict get $nets listed] ,]\nSCALING_SEGMENTS: [join [dict get $nets all_segments] ,]\n"
    append text "AUTO_FIXED_NETS: [join [dict get $nets fixed_nets] ,]\n"
    append text "NET_CELLS: [dict get $scope count]\n"
    append text "BULK_PIN_CHECK: [expr {$bulk eq "UNAVAILABLE" ? "UNAVAILABLE" : "pins=[sizeof_collection [dict get $scope primary_pins]] not_at_target=[llength $bulk_rows]"}]\n"
    append text "SAMPLE: cells=[llength $sample_names] scaling_pins_checked=[dict get $result sample_pins_checked] cells_without_scaling_pin=[dict get $result sample_cells_unverified]\n"
    append text "FIXED_NET_CONTROLS: cells=[llength $control_names] pins=[dict get $result control_pins]\n"
    foreach line $errors { append text "$line\n" }
    append text "\nBEFORE SUPPLY REPORT\n[dict get $before nets]\nAFTER SUPPLY REPORT\n[dict get $after nets]\n"
    append text "\nBEFORE PIN REPORT\n[dict get $before pins]\nAFTER PIN REPORT\n[dict get $after pins]\n"
    set path [auto_scaling::detail_path $out .net_power.txt]
    auto_scaling::write_text $path $text
    if {[llength $errors]} {
        set codes [lsort -unique [regexp -all -inline {NET-00[0-9]} [join $errors " "]]]
        error "[join $codes /]: Net-mode voltage verification failed ([llength $errors] finding(s)); first: [lindex $errors 0]. A cell-level set_voltage in the restored session wins over the net: remove it (or restore a session without it) and rerun. Evidence: $path"
    }
    puts "NET POWER VERIFICATION: PASSED | nets=[join [dict get $nets listed] ,] sample_pins=[dict get $result sample_pins_checked] bulk=[expr {$bulk eq "UNAVAILABLE" ? "unavailable" : "all [sizeof_collection [dict get $scope primary_pins]] pins at target"}] | evidence=$path"
    return $path
}

# u_mem VDDPE follows the net in net mode; confirm and keep the same evidence
# file name as path mode. Control instances are on the net too, so they are
# expected to change (unlike path mode's UM-012).
proc auto_scaling_net::verify_umem_net_power {out native target before after} {
    set names [dict get $native cell_names]
    set errors {}
    set final [dict create]
    foreach row [power_pin_rows [dict get $after pins]] {
        dict set final [list [dict get $row cell] [dict get $row pin]] $row
    }
    foreach cell $names {
        set key [list $cell VDDPE]
        if {![dict exists $final $key]} {
            lappend errors "UM-011: $cell/VDDPE was not reported after the net set_voltage"
            continue
        }
        set row [dict get $final $key]
        if {![auto_scaling::same [dict get $row max] $target] ||
            ([dict get $row min] ne "" && ![auto_scaling::same [dict get $row min] $target])} {
            lappend errors "UM-011: $cell/VDDPE reports max=[dict get $row max] min=[dict get $row min], expected $target"
        }
    }
    set status [expr {[llength $errors] ? "FAILED" : "PASSED"}]
    set evidence "U_MEM_POWER_VERIFICATION: $status\nMODE: net (VDDPE follows the scaling net; no per-cell set_voltage)\nTARGET_VDDPE: $target V\nTARGET_CELLS: $names\n"
    foreach error $errors { append evidence "$error\n" }
    append evidence "\nBEFORE PIN REPORT\n[dict get $before pins]\nAFTER PIN REPORT\n[dict get $after pins]\n"
    dict for {lib record} [dict get $native groups] {
        append evidence "\nNATIVE GROUP FOR $lib; bracket=[dict get $record bracket]\n[dict get $record report]\n"
    }
    set path [auto_scaling::detail_path $out .umem_power.txt]
    auto_scaling::write_text $path $evidence
    if {[llength $errors]} { error "U_MEM power verification failed: $errors. Evidence: $path" }
    puts "U_MEM POWER VERIFICATION: PASSED (net mode) | evidence=$path"
    return $path
}

# ---------------------------------------------------------------------------
# Clock-network evidence (.clock.dcalc)
# ---------------------------------------------------------------------------

# Walk back from a register clock pin to the first driving cell that is in
# the net scope; return its input->output arc.
proc auto_scaling_net::clock_cell_arc {clock_pin scope_cells} {
    set pin $clock_pin
    for {set level 0} {$level < 64} {incr level} {
        set net [get_nets -quiet -of_objects $pin]
        if {![sizeof_collection $net]} { return {} }
        set drivers [get_pins -quiet -leaf -of_objects $net -filter {direction == out}]
        if {[sizeof_collection $drivers] != 1} { return {} }
        set cell [get_cells -quiet -of_objects $drivers]
        if {[sizeof_collection $cell] != 1} { return {} }
        set inputs [get_pins -quiet -of_objects $cell -filter {direction == in}]
        if {![sizeof_collection $inputs]} { return {} }
        set input ""
        foreach_in_collection candidate $inputs {
            if {![catch {get_attribute -quiet $candidate clocks} clocks] &&
                $clocks ne "" && [sizeof_collection $clocks]} {
                set input $candidate
                break
            }
        }
        if {$input eq ""} { set input [index_collection $inputs 0] }
        if {[sizeof_collection [remove_from_collection -intersect $cell $scope_cells]]} {
            return [dict create from $input to $drivers cell [get_object_name $cell] level $level]
        }
        set pin $input
    }
    return {}
}

proc auto_scaling_net::verify_clock_scaling {out fixed delay_type pba_mode scaled_cells scope_cells} {
    set evidence [auto_scaling::detail_path $out .clock.dcalc]
    auto_scaling::write_text $evidence "CLOCK_SCALING_VERIFICATION_STATUS: STARTED\n"
    set path [auto_scaling::find_scaling_fixed_path $fixed $delay_type $pba_mode $scaled_cells]
    set clock_pins {}
    set startpoint [get_attribute -quiet $path startpoint]
    if {$startpoint ne "" && [sizeof_collection $startpoint] &&
        [get_attribute -quiet $startpoint is_clock_pin] eq "true"} {
        lappend clock_pins [list launch $startpoint]
    }
    set endpoint [get_attribute -quiet $path endpoint]
    if {$endpoint ne "" && [sizeof_collection $endpoint]} {
        set capture_cell [get_cells -quiet -of_objects $endpoint]
        if {[sizeof_collection $capture_cell] == 1} {
            set capture [get_pins -quiet -of_objects $capture_cell -filter {is_clock_pin == true}]
            if {[sizeof_collection $capture]} { lappend clock_pins [list capture [index_collection $capture 0]] }
        }
    }
    set arc {}
    foreach item $clock_pins {
        lassign $item side pin
        set arc [clock_cell_arc $pin $scope_cells]
        if {$arc ne ""} { dict set arc side $side; dict set arc sink [get_object_name $pin]; break }
    }
    if {$arc eq ""} {
        auto_scaling::write_text $evidence "CLOCK_SCALING_VERIFICATION_STATUS: SKIPPED\nREASON: no clock-network cell on the scaling net drives the evidence path's clock pins\n"
        puts "CLOCK SCALING VERIFICATION: SKIPPED (no clock-network cell on the scaling net for the evidence path) | evidence=$evidence"
        return $evidence
    }
    set text ""
    if {[catch {
        redirect -variable text {
            report_delay_calculation -$delay_type -from [dict get $arc from] -to [dict get $arc to]
        }
    } problem]} {
        auto_scaling::write_text $evidence "CLOCK_SCALING_VERIFICATION_STATUS: FAILED\nRUN ERROR: SV-002: $problem\n"
        error "SV-002: report_delay_calculation failed on clock cell [dict get $arc cell]: $problem. Evidence: $evidence"
    }
    set head "SIDE: [dict get $arc side]\nSINK_CLOCK_PIN: [dict get $arc sink]\nCLOCK_CELL: [dict get $arc cell] (levels_from_sink=[dict get $arc level])\nFROM_PIN: [get_object_name [dict get $arc from]]\nTO_PIN: [get_object_name [dict get $arc to]]\nANALYSIS_DELAY_TYPE: $delay_type\n"
    if {[regexp -nocase {SLG-320|DEL-012|scaling extrapolation problem|due to extrapolation in scaling} $text]} {
        auto_scaling::write_text $evidence "CLOCK_SCALING_VERIFICATION_STATUS: FAILED\nRUN ERROR: SV-003\n$head$text"
        error "SV-003: Scaling extrapolation/cancellation on clock cell [dict get $arc cell]. Evidence: $evidence"
    }
    if {[string first "Scaling libraries used" $text] < 0} {
        auto_scaling::write_text $evidence "CLOCK_SCALING_VERIFICATION_STATUS: FAILED\nRUN ERROR: SV-004\n$head$text"
        error "SV-004: Clock cell [dict get $arc cell] shows no 'Scaling libraries used'; the clock tree was not scaled. Evidence: $evidence"
    }
    auto_scaling::write_text $evidence "CLOCK_SCALING_VERIFICATION_STATUS: PASSED\n$head$text"
    puts "CLOCK SCALING VERIFICATION: PASSED | cell=[dict get $arc cell] side=[dict get $arc side] | evidence=$evidence"
    return $evidence
}

# ---------------------------------------------------------------------------
# Main flow (copy of auto_scaling::run_after_restore with net-mode changes)
# ---------------------------------------------------------------------------

proc auto_scaling_net::run_after_restore {cfg} {
    set ::auto_scaling::last_library_scope {}
    foreach command {
        get_designs get_libs get_lib_cells current_design define_scaling_lib_group
        report_lib_groups get_supply_nets get_pg_pins get_cells filter_collection
        report_power_pin_info report_supply_net remove_from_collection add_to_collection
        set_temperature set_voltage update_timing get_timing_paths
    } {
        if {![llength [info commands ::$command]]} {
            error "Source this file in pt_shell after restore_session."
        }
    }
    check_config $cfg
    if {![sizeof_collection [get_designs -quiet *]]} {
        error "No restored design was found. Run restore_session <session_directory> first."
    }
    if {![sizeof_collection [get_libs -quiet *]]} {
        error "No restored libraries were found. Check restore_session."
    }
    set out [actual_report $cfg]
    reset_net_sidecars $out
    puts "SCALING MODE: net | report=$out"

    set restored_cfg $cfg
    set phase_started [auto_scaling::phase_start VERIFY_POWER_NETS]
    set roles [auto_scaling::resolve_configured_supply_roles $cfg]
    set nets [resolve_scaling_nets $roles]
    set roles [apply_segment_roles $roles $nets]
    dict set restored_cfg configured_supply_roles $roles
    puts "NET MODE SCALING NETS: [join [dict get $nets listed] ,] | segments=[llength [dict get $nets all_segments]] | auto-fixed=[llength [dict get $nets fixed_nets]]"
    auto_scaling::phase_done VERIFY_POWER_NETS $phase_started

    set phase_started [auto_scaling::phase_start VERIFY_PARASITICS]
    if {[dict exists $restored_cfg spef_template]} { dict unset restored_cfg spef_template }
    if {[dict exists $restored_cfg spef]} { dict unset restored_cfg spef }
    set parasitics [auto_scaling::verify_restored_parasitics $restored_cfg]
    auto_scaling::phase_done VERIFY_PARASITICS $phase_started

    set phase_started [auto_scaling::phase_start CLASSIFY_FIXED_PATH_SUPPLY]
    set fixed [auto_scaling::read_fixed [auto_scaling::need $cfg fixed_tcl] [auto_scaling::option $cfg delay_type max]]
    set supply [auto_scaling::classify_fixed_path_supply $fixed $restored_cfg]
    puts "NET MODE: the line above is the fixed-path classification; set_voltage applies to the whole net."
    auto_scaling::audit_fixed_path_group_targets $supply $restored_cfg
    # VDDPE follows the net, so an empty TARGET_VDDPE_VOLTAGE means TARGET_VOLTAGE.
    if {[catch {auto_scaling::native_umem_scope $supply $restored_cfg} native_umem options]} {
        if {[string match "UM-001:*" $native_umem] &&
            [string trim [auto_scaling::option $restored_cfg target_vddpe ""]] eq ""} {
            dict set restored_cfg target_vddpe [format %.12g [auto_scaling::number [dict get $cfg target_v]]]
            puts "NET MODE: u_mem VDDPE follows the scaling net; TARGET_VDDPE_VOLTAGE = TARGET_VOLTAGE = [dict get $restored_cfg target_vddpe] V"
            set native_umem [auto_scaling::native_umem_scope $supply $restored_cfg]
        } else {
            return -options $options $native_umem
        }
    }
    dict set fixed cell_names [get_object_name [dict get $supply path_cells]]
    dict set restored_cfg resolved_fixed $fixed
    dict set restored_cfg native_umem $native_umem
    auto_scaling::phase_done CLASSIFY_FIXED_PATH_SUPPLY $phase_started

    set phase_started [auto_scaling::phase_start NET_SCOPE_AUDIT]
    set scope [net_scope_audit $nets $supply $native_umem $out]
    # The planner now picks library families for every cell on the net.
    dict set supply target_cells [dict get $scope cells]
    dict set restored_cfg fixed_path_supply $supply
    auto_scaling::phase_done NET_SCOPE_AUDIT $phase_started

    set phase_started [auto_scaling::phase_start PLAN_DESIGN_LIBRARIES]
    set plan [auto_scaling::plan $restored_cfg]
    dict set plan restored_parasitics $parasitics
    set fixed [expr {[dict exists $plan fixed] ? [dict get $plan fixed] : ""}]
    dict set restored_cfg fixed_library_rows [dict get $plan fixed_library_rows]
    set fixed_restore [auto_scaling::validate_fixed_restore_libraries $fixed $restored_cfg]
    set nearest_bindings [auto_scaling::plan_nearest_bindings $fixed $restored_cfg $plan]
    if {[llength $nearest_bindings]} { error "NET-010: Nearest DB bindings are not supported in net mode." }
    dict set restored_cfg fixed_library_names [dict get $fixed_restore names]
    set scaling_library_names {}
    foreach row [dict get $plan scaling_library_rows] {
        lappend scaling_library_names [dict get $row lib_name]
    }
    set scaling_library_names [concat $scaling_library_names [dict get $native_umem library_names]]
    dict set restored_cfg scaling_library_names [lsort -unique $scaling_library_names]
    dict set plan fixed_restore_records [dict get $fixed_restore records]
    set dt [auto_scaling::option $cfg delay_type max]
    if {$dt ni {max min}} { error "delay_type must be max or min" }

    auto_scaling::reset_output_files $out
    file mkdir [file dirname $out]
    set inputs_text [auto_scaling::scaling_inputs_text $plan]
    append inputs_text "SCALING_SCOPE mode=net nets=[join [dict get $nets listed] ,] net_cells=[dict get $scope count]\n"
    auto_scaling::write_text [auto_scaling::detail_path $out .inputs.txt] $inputs_text
    puts $inputs_text
    # LOO guard TL-001 (from the original): stop before groups or V/T change.
    set target_corner_dbs [auto_scaling::loo_check_linked $plan $supply $out]
    auto_scaling::phase_done PLAN_DESIGN_LIBRARIES $phase_started

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

    set phase_started [auto_scaling::phase_start PREPARE_SCALING_GROUPS]
    redirect -variable groups_before {
        report_lib_groups -scaling -nosplit -show {voltage temperature process}
    }
    auto_scaling::write_text [auto_scaling::detail_path $out .libgroups.before] $groups_before
    set has_existing_group [regexp -line {^Group[[:space:]]+[0-9]+} $groups_before]
    if {$has_existing_group} {
        if {[auto_scaling::report_has_unapproved_corner $groups_before $plan $rail $target_v $target_t]} {
            error "An existing non-exempt scaling group contains or rounds to target $target_v V/$target_t C. Target-excluded scaling cannot be proven with this group. $::auto_scaling::last_corner_detail. For a multirail line, check whether the matched rail is a pin on the scaling net (real) or a fixed rail (coincidence)."
        }
        puts "RESTORE MODE: Reusing existing scaling groups."
        if {[auto_scaling::option $cfg create_missing_scaling_groups 0]} {
            auto_scaling::define_missing_scalar_groups $scaling_sets
        }
    } else {
        puts "RESTORE MODE: Creating [llength $scaling_sets] scaling groups with the target corner excluded."
        foreach scaling_set $scaling_sets {
            set set_name [dict get $scaling_set name]
            set dbs [dict get $scaling_set dbs]
            puts "DEFINE SCALING LIBRARY SET: $set_name"
            set failed [catch {define_scaling_lib_group $dbs} status]
            if {$failed || $status ne "1"} {
                error "Scaling group creation failed ($set_name): status=$status. Check that the DBs model the same cells/pins."
            }
        }
    }
    redirect -variable groups_after {
        report_lib_groups -scaling -nosplit -show {voltage temperature process}
    }
    auto_scaling::write_text [auto_scaling::detail_path $out .libgroups] $groups_after
    if {[auto_scaling::report_has_unapproved_corner $groups_after $plan $rail $target_v $target_t]} {
        error "A non-exempt scaling group still contains or rounds to the target corner. $::auto_scaling::last_corner_detail. Scaling verification failed: [auto_scaling::detail_path $out .libgroups]"
    }
    auto_scaling::verify_planned_group_coverage $plan
    # LOO guard TL-003 (from the original), then NET-001.
    auto_scaling::loo_check_groups $plan $target_corner_dbs $out
    check_net_groups $scope $plan $out
    auto_scaling::phase_done PREPARE_SCALING_GROUPS $phase_started

    set phase_started [auto_scaling::phase_start CLASSIFY_FIXED_PATH_POWER]
    set power_plan [auto_scaling::plan_fixed_path_power $fixed $restored_cfg]
    set scaled_cells [dict get $power_plan scaled_cells]
    auto_scaling::phase_done CLASSIFY_FIXED_PATH_POWER $phase_started

    set phase_started [auto_scaling::phase_start APPLY_NET_VOLTAGE_TEMP]
    apply_net_voltage $scope $scaled_cells $native_umem $target_v $target_t $out
    auto_scaling::phase_done APPLY_NET_VOLTAGE_TEMP $phase_started

    set phase_started [auto_scaling::phase_start UPDATE_TIMING_SI_POCV]
    auto_scaling::check_status update_timing {update_timing}
    auto_scaling::phase_done UPDATE_TIMING_SI_POCV $phase_started

    set phase_started [auto_scaling::phase_start GENERATE_TIMING_REPORT]
    set fp [open [auto_scaling::detail_path $out .selection.tcl] w]
    puts $fp "# restore_session scaling selection record (net mode)"
    set record $plan
    dict unset record fixed paths
    if {[dict exists $record fixed cell_names]} { dict unset record fixed cell_names }
    if {[dict exists $record native_umem groups]} {
        dict for {lib group_record} [dict get $record native_umem groups] {
            dict unset record native_umem groups $lib report
        }
    }
    dict set record restored_design [get_object_name [current_design]]
    dict set record scaling_scope net
    dict set record fixed_power_nets [dict get $nets fixed_nets]
    dict set record scaling_power_nets [dict get $nets listed]
    dict set record scaling_net_segments [dict get $nets all_segments]
    dict set record net_cell_count [dict get $scope count]
    dict set record scaled_cell_count [sizeof_collection $scaled_cells]
    puts $fp [list set scaling_selection $record]
    close $fp

    set fp [open $out w]
    puts $fp "### SCALING TARGET process=[dict get $plan process] voltage=[dict get $plan v] temperature=[dict get $plan t] beol=[dict get $plan beol] axis=[dict get $plan mode]"
    puts $fp "### RESTORED PARASITIC corner_name=[dict get $parasitics corner_name] temperature=[dict get $parasitics temperature]"
    puts $fp "### SCALING SCOPE mode=net net=[join [dict get $nets listed] ,] net_cells=[dict get $scope count]"
    puts $fp ""
    close $fp

    set fixed_result [auto_scaling::report_fixed_paths $out [dict get $fixed paths] \
        $dt [auto_scaling::option $cfg pba_mode ""]]
    if {![file exists $out] || [file size $out] == 0} {
        error "Timing report was not created or is empty: $out"
    }
    auto_scaling::phase_done GENERATE_TIMING_REPORT $phase_started

    set phase_started [auto_scaling::phase_start VERIFY_SCALING_RESULT]
    set core_names {}
    foreach name [get_object_name $scaled_cells] {
        if {[lsearch -exact [dict get $native_umem cell_names] $name] < 0} { lappend core_names $name }
    }
    if {[llength $core_names]} {
        auto_scaling::verify_scaling_result $out $fixed $dt [auto_scaling::option $cfg pba_mode ""] \
            [get_cells -quiet -exact $core_names]
        verify_clock_scaling $out $fixed $dt [auto_scaling::option $cfg pba_mode ""] \
            [get_cells -quiet -exact $core_names] [dict get $scope cells]
    }
    if {[llength [dict get $native_umem cell_names]]} {
        auto_scaling::verify_scaling_result $out $fixed $dt [auto_scaling::option $cfg pba_mode ""] \
            [get_cells -quiet -exact [dict get $native_umem cell_names]] .umem.dcalc
    }
    auto_scaling::phase_done VERIFY_SCALING_RESULT $phase_started

    puts "DONE: restore-session net-mode scaling report = $out"
    puts "FIXED PATH SUMMARY: requested=[dict get $fixed_result requested] measured=[dict get $fixed_result measured] missing=[dict get $fixed_result missing]"
    puts "VERIFY: net scope = [auto_scaling::detail_path $out .net_scope.txt]"
    puts "VERIFY: net power = [auto_scaling::detail_path $out .net_power.txt]"
    if {[llength $core_names]} {
        puts "VERIFY: scaling library evidence = [auto_scaling::detail_path $out .dcalc]"
        puts "VERIFY: clock-network evidence = [auto_scaling::detail_path $out .clock.dcalc]"
    }
    if {[llength [dict get $native_umem cell_names]]} {
        puts "VERIFY: u_mem scaling evidence = [auto_scaling::detail_path $out .umem.dcalc]"
        puts "VERIFY: u_mem PG/supply evidence = [auto_scaling::detail_path $out .umem_power.txt]"
    }
    return $out
}

proc auto_scaling_net::run_after_restore_monitored {cfg} {
    auto_scaling::start_progress_monitor [auto_scaling::option $cfg progress_minutes 10]
    set code [catch {run_after_restore $cfg} result options]
    if {$code} {
        auto_scaling::stop_progress_monitor FAILED
    } else {
        auto_scaling::stop_progress_monitor SUCCESS
    }
    if {$code} { return -options $options $result }
    return $result
}

proc auto_scaling_net::run_config_with_log {scaling_config} {
    check_config $scaling_config
    dict set scaling_config out_rpt [net_report_name [dict get $scaling_config out_rpt]]
    set actual_out [actual_report $scaling_config]
    set log_file [auto_scaling::detail_path $actual_out .log]
    file mkdir [file dirname $log_file]
    set previous_count [auto_scaling::reset_output_files $actual_out 1]
    incr previous_count [reset_net_sidecars $actual_out]
    set code [catch {
        redirect -tee -file $log_file {
            puts "OUTPUT MODE: overwrite | previous_files_removed=$previous_count"
            set scaling_result [run_after_restore_monitored $scaling_config]
            puts "RUN COMPLETE: Restored-session net-mode scaling and fixed-path reporting finished."
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
    set net_scaling_config [auto_scaling_net::build_config]
    set net_scaling_result [auto_scaling_net::run_config_with_log $net_scaling_config]
}
