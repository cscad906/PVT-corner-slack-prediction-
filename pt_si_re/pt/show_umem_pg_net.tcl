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
# Read-only: no voltage, temperature, library, group, timing or file changes.
# ASCII source/output avoids UTF-8/EUC-KR source-encoding problems.

# USER SETTINGS
set UMEM_CELL_PATTERN "*u_mem*"   ;# leaf cell name pattern, or one exact instance
set UMEM_PG_PIN_NAME  "VDDPE"     ;# PG pin to inspect
set UMEM_MAX_ROWS     20          ;# per-cell rows to print; the summary counts all
# END USER SETTINGS

namespace eval umem_pg_net {}

proc umem_pg_net::show {pattern pin_name max_rows} {
    foreach command {get_cells get_pg_pins get_supply_nets get_lib_cells get_libs} {
        if {![llength [info commands ::$command]]} {
            error "PGN-001: '$command' is missing. Source this in pt_shell after restore_session."
        }
    }
    if {![sizeof_collection [get_designs -quiet *]]} {
        error "PGN-001: No design is loaded. Run restore_session first."
    }
    set cells [get_cells -quiet -hierarchical $pattern -filter "is_hierarchical==false"]
    if {![sizeof_collection $cells]} {
        error "PGN-002: No leaf cell matches '$pattern'. Check the instance name in a timing report."
    }
    puts "PG NET QUERY: pattern=$pattern pg_pin=$pin_name leaf_cells=[sizeof_collection $cells]"

    set by_net [dict create]
    set no_pin 0
    set shown 0
    foreach_in_collection cell $cells {
        set name [get_object_name $cell]
        set pg [get_pg_pins -quiet -of_objects $cell -filter "pin_name==$pin_name"]
        if {$pg eq "" || ![sizeof_collection $pg]} {
            incr no_pin
            continue
        }
        set nets [get_supply_nets -quiet -of_objects $pg]
        if {$nets ne "" && [sizeof_collection $nets]} {
            set net [join [get_attribute $nets full_name] ","]
        } else {
            set net "NONE"
        }
        set conn [get_attribute -quiet $pg supply_connection]
        set type [get_attribute -quiet $pg type]
        dict lappend by_net $net $name
        if {$shown < $max_rows} {
            set ref [get_attribute -quiet $cell ref_name]
            set lib_cell [get_lib_cells -quiet -of_objects $cell]
            set lib ""
            if {$lib_cell ne "" && [sizeof_collection $lib_cell]} {
                set lib [get_object_name [get_libs -quiet -of_objects $lib_cell]]
            }
            puts "CELL=$name | ref=$ref | lib=$lib"
            puts "  $pin_name type=$type | net=$net | supply_connection=$conn"
            incr shown
        }
    }
    if {$shown < [sizeof_collection $cells] - $no_pin} {
        puts "  ... [expr {[sizeof_collection $cells] - $no_pin - $shown}] more cell(s) not printed (UMEM_MAX_ROWS=$max_rows)"
    }

    puts "SUMMARY: cells_with_$pin_name=[expr {[sizeof_collection $cells] - $no_pin}] cells_without_$pin_name=$no_pin"
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

umem_pg_net::show $UMEM_CELL_PATTERN $UMEM_PG_PIN_NAME $UMEM_MAX_ROWS
