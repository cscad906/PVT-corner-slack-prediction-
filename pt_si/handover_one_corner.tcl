# =====================================================================
# handover_one_corner.tcl
# PrimeTime one-corner run: timing report + crosstalk attribute dump.
#
#   pt_shell -f handover_one_corner.tcl
#
# Requires PrimeTime SI (si_enable_analysis) and a SPEF extracted with
# coupling capacitance preserved (StarRC COUPLING_CAP: YES).
# Verified on PrimeTime V-2023.12-SP4.
#
# Returns two files:
#   $OUT_RPT   timing report
#   $OUT_TSV   crosstalk / timing-window table (tab separated)
# =====================================================================

# --------------------------------------------------------------- INPUTS
set TOP      "MyCoreTop"
set VERILOG  "/path/to/design.v"
set SDC      "/path/to/design.sdc"
set SPEF     "/path/to/design.Cnom_25.spef"
set LIB_DB   "/path/to/corner.db"

set OUT_RPT  "/path/to/out/corner.rpt"
set OUT_TSV  "/path/to/out/corner.xtalk.tsv"

set DTYPE    "max"      ;# setup = max, hold = min
set NWORST   3          ;# setup = 3, hold = 10
set MAXPATHS 3000
set SLACK_TH 0.05       ;# SDC time unit (ns) -- paths with slack < this

# --------------------------------------------------------------- CHECK
foreach f [list $VERILOG $SDC $SPEF $LIB_DB] {
  if {![file exists $f]} {
    puts stderr "ERROR: missing input file: $f"
    exit 1
  }
}
file mkdir [file dirname $OUT_RPT]
file mkdir [file dirname $OUT_TSV]

# --------------------------------------------------------------- SETUP
set_app_var si_enable_analysis true
set_app_var timing_save_pin_arrival_and_slack true

read_verilog $VERILOG
current_design $TOP
set link_path "* $LIB_DB"
link_design
read_sdc $SDC
read_parasitics -keep_capacitive_coupling $SPEF
set_propagated_clock [all_clocks]
update_timing

# --------------------------------------------------------------- 1. TIMING REPORT
redirect -file $OUT_RPT {
  report_timing -delay_type $DTYPE -path_type full_clock_expanded \
    -nets -capacitance -transition_time -input_pins \
    -nosplit -significant_digits 4 \
    -nworst $NWORST -max_paths $MAXPATHS -slack_lesser_than $SLACK_TH
}
puts "DONE: timing report -> $OUT_RPT"

# --------------------------------------------------------------- 2. CROSSTALK ATTRIBUTES
proc A {obj attr} {
  if {$obj eq ""} { return "" }
  if {[catch {get_attribute $obj $attr} v]} { return "" }
  return $v
}

proc NAMES {coll} {
  if {$coll eq ""} { return "" }
  set r {}
  if {[catch {foreach_in_collection c $coll { lappend r [get_object_name $c] }}]} { return "" }
  return [join $r ","]
}

set paths [get_timing_paths -delay_type $DTYPE \
             -nworst $NWORST -max_paths $MAXPATHS -slack_lesser_than $SLACK_TH]

set fh [open $OUT_TSV w]
puts $fh [join {
  path_idx slack net load_pin
  delta_max delta_min n_aggr n_eff_aggr coup_cap eff_coup_cap
  bumps bump_max_rise bump_max_fall bump_min_rise bump_min_fall aggressors
  min_rise_arr max_rise_arr min_fall_arr max_fall_arr rise_slew fall_slew
} "\t"]

set pidx 0
set nrow 0
foreach_in_collection p $paths {
  incr pidx
  set slack [A $p slack]
  foreach_in_collection tp [get_attribute $p points] {
    set obj [A $tp object]
    if {$obj eq ""} { continue }
    set nets [get_nets -quiet -of_objects $obj]
    if {[sizeof_collection $nets] == 0} { continue }
    set n  [index_collection $nets 0]
    set nm [get_object_name $n]
    if {[info exists seen($pidx,$nm)]} { continue }
    set seen($pidx,$nm) 1
    incr nrow
    puts $fh [join [list \
      $pidx $slack $nm [get_object_name $obj] \
      [A $n annotated_delay_delta_max] \
      [A $n annotated_delay_delta_min] \
      [A $n number_of_aggressors] \
      [A $n number_of_effective_aggressors] \
      [A $n total_coupling_capacitance] \
      [A $n total_effective_coupling_capacitance] \
      [A $n si_xtalk_bumps] \
      [A $n si_xtalk_bumps_max_rise] \
      [A $n si_xtalk_bumps_max_fall] \
      [A $n si_xtalk_bumps_min_rise] \
      [A $n si_xtalk_bumps_min_fall] \
      [NAMES [A $n effective_aggressors]] \
      [A $obj min_rise_arrival] \
      [A $obj max_rise_arrival] \
      [A $obj min_fall_arrival] \
      [A $obj max_fall_arrival] \
      [A $obj actual_rise_transition_max] \
      [A $obj actual_fall_transition_max] \
    ] "\t"]
  }
}
close $fh

puts "DONE: crosstalk table -> $OUT_TSV"
puts "STATS: paths=$pidx rows=$nrow"
exit
