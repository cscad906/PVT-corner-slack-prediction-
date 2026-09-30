# Show which supply net a macro's PG pin (e.g. u_mem/VDDPE) is connected to.
#
# Usage in pt_shell AFTER restore_session:
#   source /absolute/path/to/pt/show_umem_pg_net.tcl
#
# Why: VDDPE is the macro's Liberty PG pin name, not a UPF supply net name.
# run_scaling_after_restore.tcl decides whether a cell is scaled by the supply
# net its primary PG pin is connected to. If u_mem/VDDPE is connected to the
# core net, set SCALING_POWER_NET to that net and u_mem follows it; putting
# "VDDPE" itself in SCALING_POWER_NET(S) fails because no such net exists.
#
# Matching is on the FULL hierarchical name. "get_cells -hierarchical *u_mem*"
# only compares each level's own name, so when u_mem is a wrapper block the
# macro inside it (u_mem/u_sram_0) is never matched. Here every leaf cell
# whose full name contains the pattern is considered, and only those that
# actually have the PG pin are reported.
#
# Read-only: no voltage, temperature, library, group, timing or file changes.
# The query runs from the top level and restores the current instance after.
# ASCII source/output avoids UTF-8/EUC-KR source-encoding problems.

# USER SETTINGS
set UMEM_CELL_PATTERN "*u_mem*"   ;# full-name pattern, or one exact leaf instance
set UMEM_PG_PIN_NAME  "VDDPE"     ;# PG pin to inspect
set UMEM_MAX_ROWS     20          ;# per-cell rows to print; the summary counts all
# END USER SETTINGS

namespace eval umem_pg_net {}

proc umem_pg_net::inspect {pattern pin_name max_rows} {
    set leaves [get_cells -quiet -hierarchical * \
        -filter "full_name =~ \"$pattern\" && is_hierarchical == false"]
    set blocks [get_cells -quiet -hierarchical * \
        -filter "full_name =~ \"$pattern\" && is_hierarchical == true"]
    set n_leaf [expr {$leaves eq "" ? 0 : [sizeof_collection $leaves]}]
    set n_block [expr {$blocks eq "" ? 0 : [sizeof_collection $blocks]}]
    puts "PG NET QUERY: pattern=$pattern pg_pin=$pin_name leaf_cells=$n_leaf hierarchical_blocks=$n_block"
    if {$n_block} {
        set sample [lrange [get_object_name $blocks] 0 4]
        puts "  hierarchical blocks matching (first 5): $sample"
    }
    if {!$n_leaf} {
        error "PGN-002: No leaf cell has a full name matching '$pattern'. Names are case-sensitive; copy the instance path from a timing report, without the pin."
    }

    # get_pg_pins takes only -of_objects here (no -quiet/-filter), so filter
    # separately -- the same way run_scaling_after_restore.tcl does.
    set all_pg ""
    if {[catch {set all_pg [get_pg_pins -of_objects $leaves]} problem]} {
        error "PGN-003: get_pg_pins failed on the matching cells: $problem. The session may have no UPF power connectivity."
    }
    set pins ""
    if {$all_pg ne "" && [sizeof_collection $all_pg]} {
        set pins [filter_collection $all_pg "pin_name == $pin_name"]
    }
    set n_pin [expr {$pins eq "" ? 0 : [sizeof_collection $pins]}]
    if {!$n_pin} {
        set seen {}
        if {$all_pg ne "" && [sizeof_collection $all_pg]} {
            set seen [lsort -unique [get_attribute $all_pg pin_name]]
        }
        error "PGN-003: None of the $n_leaf matching leaf cells has a PG pin named '$pin_name'. PG pin names seen on them: [expr {[llength $seen] ? $seen : {none (no UPF PG connectivity?)}}]"
    }

    set by_net [dict create]
    set shown 0
    set suffix "/$pin_name"
    foreach_in_collection pg $pins {
        set full [get_attribute $pg full_name]
        set cell_name [string range $full 0 end-[string length $suffix]]
        set nets [get_supply_nets -quiet -of_objects $pg]
        if {$nets ne "" && [sizeof_collection $nets]} {
            set net [join [get_attribute $nets full_name] ","]
        } else {
            set net "NONE"
        }
        dict lappend by_net $net $cell_name
        if {$shown < $max_rows} {
            set cell [get_cells -quiet -exact $cell_name]
            set ref [get_attribute -quiet $cell ref_name]
            set lib ""
            set lib_cell [get_lib_cells -quiet -of_objects $cell]
            if {$lib_cell ne "" && [sizeof_collection $lib_cell]} {
                set lib [get_object_name [get_libs -quiet -of_objects $lib_cell]]
            }
            puts "CELL=$cell_name | ref=$ref | lib=$lib"
            puts "  $pin_name type=[get_attribute -quiet $pg type] | net=$net | supply_connection=[get_attribute -quiet $pg supply_connection]"
            incr shown
        }
    }
    if {$shown < $n_pin} {
        puts "  ... [expr {$n_pin - $shown}] more cell(s) not printed (UMEM_MAX_ROWS=$max_rows)"
    }

    puts "SUMMARY: leaf_cells=$n_leaf with_$pin_name=$n_pin without_$pin_name=[expr {$n_leaf - $n_pin}]"
    dict for {net names} $by_net {
        puts "  NET=$net cells=[llength $names]"
    }
    if {[dict size $by_net] == 1} {
        set only [lindex [dict keys $by_net] 0]
        if {$only ne "NONE"} {
            puts "USE: every matched $pin_name is on '$only'. If that is the core rail, set SCALING_POWER_NET \"$only\"."
        }
    } elseif {[dict size $by_net] > 1} {
        puts "NOTE: $pin_name is on more than one net. Check which of them moves with the core before scaling."
    }
    if {[dict exists $by_net NONE]} {
        puts "NOTE: some $pin_name pins have no resolved supply net; see supply_connection above."
    }
}

proc umem_pg_net::run {pattern pin_name max_rows} {
    foreach command {get_cells get_pg_pins get_supply_nets get_lib_cells get_libs
                     get_designs current_instance filter_collection} {
        if {![llength [info commands ::$command]]} {
            error "PGN-001: '$command' is missing. Source this in pt_shell after restore_session."
        }
    }
    if {![sizeof_collection [get_designs -quiet *]]} {
        error "PGN-001: No design is loaded. Run restore_session first."
    }
    # Search from the top so a scope left inside a block by another script
    # cannot hide cells; put the scope back whatever happens.
    set original_scope [current_instance .]
    set code [catch {
        current_instance
        inspect $pattern $pin_name $max_rows
    } result options]
    if {$original_scope eq ""} { current_instance } else { current_instance $original_scope }
    if {$code} { return -options $options $result }
}

umem_pg_net::run $UMEM_CELL_PATTERN $UMEM_PG_PIN_NAME $UMEM_MAX_ROWS
