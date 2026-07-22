# PrimeTime native SPICE deck smoke flow.
#
# This script loads the BoomCore timing setup, selects one fixed timing path,
# and writes a PrimeTime-generated SPICE deck with write_spice_deck.
#
# Required environment variables:
#   TOP        Top design name, e.g. BoomCore
#   VERILOG    Gate-level Verilog netlist
#   SDC        Timing constraints
#   SPEF       Parasitics for this RC corner
#   LIB_DB     PrimeTime .db timing library
#   FIXED_TCL  Tcl file defining FIXED_PATHS
#   CELL_SPF   SPICE/CDL file containing stdcell .SUBCKT definitions
#   MODEL_CARD Transistor modelcard to include in generated deck header
#   OUT_DIR    Output directory
#
# Optional environment variables:
#   EXTRA_LIBS       Additional .db files for link_path
#   FIXED_INDEX      1-based fixed path index, default 1
#   DELAY_TYPE       max|min|max_rise|max_fall|min_rise|min_fall, default max
#   VDD              Logic one voltage, default 0.8
#   VSS              Logic zero voltage, default 0.0
#   INITIAL_DELAY_NS Initial PWL delay in ns, default 1.0
#   MIN_TRAN_NS      Minimum PWL transition in ns, default 0.001
#   TRAN_STEP_NS     SPICE .tran step in ns, default 0.001
#   TRAN_SIZE_NS     SPICE .tran stop time in ns, default 5.0
#   USE_THROUGHS     Add fixed through pins to get_timing_paths, default true
#   GROUND_COUPLING  Ground coupling caps instead of writing aggressors, default true
#   OUTPUT_BASENAME  Deck basename without extension, default path_000001
#   EXTRA_SPICE_INCLUDES Space-separated SPICE include files added to deck header

proc env_required {name} {
  if {[catch {getenv $name} value]} {
    set value ""
  }
  if {$value eq ""} {
    puts "ERROR: required env var $name is empty"
    exit 2
  }
  return $value
}

proc env_default {name default_value} {
  if {[catch {getenv $name} value]} {
    set value ""
  }
  if {$value eq ""} {
    return $default_value
  }
  return $value
}

proc bool_env {name default_value} {
  set value [string tolower [env_default $name $default_value]]
  switch -exact -- $value {
    1 -
    true -
    yes -
    on { return 1 }
    default { return 0 }
  }
}

proc ensure_file {label path} {
  if {![file exists $path]} {
    puts "ERROR: $label does not exist: $path"
    exit 2
  }
}

proc write_header_file {header_file model_card cell_spf extra_spice_includes vdd_value vss_value} {
  set f [open $header_file "w"]
  puts $f "* PrimeTime native write_spice_deck smoke-test header"
  puts $f ".global VDD VSS vdd vss"
  puts $f ".param VDD=$vdd_value"
  puts $f ".param VSS=$vss_value"
  puts $f "* Supply sources are emitted by write_spice_deck."
  puts $f "* Stdcell subcircuits are included by write_spice_deck -sub_circuit_file."
  puts $f ".lib '$model_card' T_nfet"
  puts $f ".lib '$model_card' T_pfet"
  puts $f ".lib '$model_card' T_nfet_15"
  puts $f ".lib '$model_card' T_pfet_15"
  puts $f ".lib '$model_card' T_nfet_18"
  puts $f ".lib '$model_card' T_pfet_18"
  puts $f ".lib '$model_card' T_n08_lvt"
  puts $f ".lib '$model_card' T_p08_lvt"
  puts $f ".lib '$model_card' T_n08_slvt"
  puts $f ".lib '$model_card' T_p08_slvt"
  puts $f ".lib '$model_card' T_n08_hvt"
  puts $f ".lib '$model_card' T_p08_hvt"
  puts $f ".lib '$model_card' T_nd"
  puts $f ".lib '$model_card' T_tond"
  puts $f ".lib '$model_card' T_pd"
  puts $f ".lib '$model_card' T_topd"
  puts $f ".lib '$model_card' T_res"
  puts $f ".lib '$model_card' T_pres"
  puts $f ".lib '$model_card' FIN"
  puts $f ".lib '$model_card' cap"
  foreach include_file $extra_spice_includes {
    puts $f ".include \"$include_file\""
  }
  close $f
}

proc safe_set_app_var {name value} {
  if {[catch {set_app_var $name $value} msg]} {
    puts "WARN: could not set app var $name=$value: $msg"
  } else {
    puts "INFO: set_app_var $name $value"
  }
}

proc fixed_path_output_name {out_dir path_key fixed_index output_basename} {
  if {$output_basename ne ""} {
    return [file join $out_dir "${output_basename}.sp"]
  }
  return [file join $out_dir [format "path_%06d.sp" $fixed_index]]
}

set TOP        [env_required TOP]
set VERILOG    [env_required VERILOG]
set SDC        [env_required SDC]
set SPEF       [env_required SPEF]
set LIB_DB     [env_required LIB_DB]
set FIXED_TCL  [env_required FIXED_TCL]
set CELL_SPF   [env_required CELL_SPF]
set MODEL_CARD [env_required MODEL_CARD]
set OUT_DIR    [env_required OUT_DIR]

set EXTRA_LIBS       [env_default EXTRA_LIBS ""]
set FIXED_INDEX      [expr {int([env_default FIXED_INDEX 1])}]
set DELAY_TYPE       [env_default DELAY_TYPE max]
set VDD              [env_default VDD 0.8]
set VSS              [env_default VSS 0.0]
set INITIAL_DELAY_NS [env_default INITIAL_DELAY_NS 1.0]
set MIN_TRAN_NS      [env_default MIN_TRAN_NS 0.001]
set TRAN_STEP_NS     [env_default TRAN_STEP_NS 0.001]
set TRAN_SIZE_NS     [env_default TRAN_SIZE_NS 5.0]
set USE_THROUGHS     [bool_env USE_THROUGHS true]
set GROUND_COUPLING  [bool_env GROUND_COUPLING true]
set ALIGN_AGGRESSORS [bool_env ALIGN_AGGRESSORS false]
set OUTPUT_BASENAME  [env_default OUTPUT_BASENAME ""]
set EXTRA_SPICE_INCLUDES [env_default EXTRA_SPICE_INCLUDES ""]
set EXTRA_SPICE_INCLUDE_LIST {}
foreach include_file [split $EXTRA_SPICE_INCLUDES " "] {
  set include_file [string trim $include_file]
  if {$include_file ne ""} {
    lappend EXTRA_SPICE_INCLUDE_LIST $include_file
  }
}

foreach pair [list \
  [list VERILOG $VERILOG] \
  [list SDC $SDC] \
  [list SPEF $SPEF] \
  [list LIB_DB $LIB_DB] \
  [list FIXED_TCL $FIXED_TCL] \
  [list CELL_SPF $CELL_SPF] \
  [list MODEL_CARD $MODEL_CARD]] {
  ensure_file [lindex $pair 0] [lindex $pair 1]
}
foreach include_file $EXTRA_SPICE_INCLUDE_LIST {
  ensure_file EXTRA_SPICE_INCLUDE $include_file
}

file mkdir $OUT_DIR
set header_file [file join $OUT_DIR "pt_native_header.sp"]
set summary_file [file join $OUT_DIR "pt_native_smoke_summary.txt"]
write_header_file $header_file $MODEL_CARD $CELL_SPF $EXTRA_SPICE_INCLUDE_LIST $VDD $VSS

puts "INFO: TOP=$TOP"
puts "INFO: VERILOG=$VERILOG"
puts "INFO: SDC=$SDC"
puts "INFO: SPEF=$SPEF"
puts "INFO: LIB_DB=$LIB_DB"
puts "INFO: FIXED_TCL=$FIXED_TCL"
puts "INFO: CELL_SPF=$CELL_SPF"
puts "INFO: EXTRA_SPICE_INCLUDES=$EXTRA_SPICE_INCLUDES"
puts "INFO: OUT_DIR=$OUT_DIR"
puts "INFO: FIXED_INDEX=$FIXED_INDEX DELAY_TYPE=$DELAY_TYPE USE_THROUGHS=$USE_THROUGHS"

safe_set_app_var si_enable_analysis true
safe_set_app_var timing_disable_cond_default_arcs true
safe_set_app_var timing_report_use_worst_parallel_cell_arc false
safe_set_app_var delay_calc_waveform_analysis_mode full_design
safe_set_app_var timing_keep_waveform_on_points true

read_verilog $VERILOG
current_design $TOP

if {$EXTRA_LIBS ne ""} {
  set link_path "* $LIB_DB $EXTRA_LIBS"
} else {
  set link_path "* $LIB_DB"
}

link_design
read_sdc $SDC
read_parasitics -keep_capacitive_coupling $SPEF
set_propagated_clock [all_clocks]
update_timing

source $FIXED_TCL
if {![info exists FIXED_PATHS]} {
  puts "ERROR: FIXED_TCL did not define FIXED_PATHS"
  exit 2
}
if {$FIXED_INDEX < 1 || $FIXED_INDEX > [llength $FIXED_PATHS]} {
  puts "ERROR: FIXED_INDEX $FIXED_INDEX out of range 1..[llength $FIXED_PATHS]"
  exit 2
}

set item [lindex $FIXED_PATHS [expr {$FIXED_INDEX - 1}]]
set path_key [lindex $item 0]
set from_pin [lindex $item 1]
set to_pin   [lindex $item 2]
set thr_list [lindex $item 3]

puts "INFO: path_key=$path_key"
puts "INFO: from_pin=$from_pin"
puts "INFO: to_pin=$to_pin"
puts "INFO: through_count=[llength $thr_list]"

set from_obj [get_pins -quiet $from_pin]
set to_obj   [get_pins -quiet $to_pin]
if {[sizeof_collection $from_obj] == 0} {
  puts "ERROR: from pin not found: $from_pin"
  exit 3
}
if {[sizeof_collection $to_obj] == 0} {
  puts "ERROR: to pin not found: $to_pin"
  exit 3
}

set timing_cmd [list get_timing_paths \
  -from $from_obj \
  -to $to_obj \
  -max_paths 1 \
  -nworst 1 \
  -pba_mode path \
  -delay_type $DELAY_TYPE]

if {$USE_THROUGHS} {
  foreach tp $thr_list {
    set tp_obj [get_pins -quiet $tp]
    if {[sizeof_collection $tp_obj] == 0} {
      puts "WARN: through pin not found, skipping: $tp"
    } else {
      lappend timing_cmd -through $tp_obj
    }
  }
}

set timing_path [eval $timing_cmd]
if {[sizeof_collection $timing_path] == 0} {
  puts "ERROR: get_timing_paths returned no path"
  puts "INFO: retrying without through pins"
  set timing_path [get_timing_paths \
    -from $from_obj \
    -to $to_obj \
    -max_paths 1 \
    -nworst 1 \
    -pba_mode path \
    -delay_type $DELAY_TYPE]
}
if {[sizeof_collection $timing_path] == 0} {
  puts "ERROR: no timing path found for selected fixed path"
  exit 4
}

if {$OUTPUT_BASENAME ne ""} {
  set report_file [file join $OUT_DIR "${OUTPUT_BASENAME}.rpt"]
} else {
  set report_file [file join $OUT_DIR "path_000001.rpt"]
}
set report_cmd [list report_timing \
  -path_type full_clock_expanded \
  -from $from_obj \
  -to $to_obj \
  -max_paths 1 \
  -sort_by slack \
  -input_pins \
  -nets \
  -capacitance \
  -transition_time \
  -nosplit \
  -significant_digits 4]
if {$USE_THROUGHS} {
  foreach tp $thr_list {
    set tp_obj [get_pins -quiet $tp]
    if {[sizeof_collection $tp_obj] > 0} {
      lappend report_cmd -through $tp_obj
    }
  }
}
redirect $report_file {
  puts "### PT_NATIVE_SMOKE_PATH idx=$FIXED_INDEX key=$path_key"
  eval $report_cmd
}

set output_file [fixed_path_output_name $OUT_DIR $path_key $FIXED_INDEX $OUTPUT_BASENAME]
set spice_cmd [list write_spice_deck \
  -output $output_file \
  -header $header_file \
  -logic_one_voltage $VDD \
  -logic_zero_voltage $VSS \
  -logic_one_name VDD \
  -logic_zero_name VSS \
  -initial_delay $INITIAL_DELAY_NS \
  -minimum_transition_time $MIN_TRAN_NS \
  -transient_step $TRAN_STEP_NS \
  -transient_size $TRAN_SIZE_NS \
  -sub_circuit_file $CELL_SPF]

if {$GROUND_COUPLING} {
  lappend spice_cmd -ground_coupling_capacitors
}
if {$ALIGN_AGGRESSORS} {
  lappend spice_cmd -align_aggressors
}
lappend spice_cmd $timing_path

puts "INFO: running write_spice_deck -> $output_file"
set status [eval $spice_cmd]
puts "INFO: write_spice_deck status=$status"

set sf [open $summary_file "w"]
puts $sf "status=$status"
puts $sf "top=$TOP"
puts $sf "fixed_index=$FIXED_INDEX"
puts $sf "path_key=$path_key"
puts $sf "from_pin=$from_pin"
puts $sf "to_pin=$to_pin"
puts $sf "through_count=[llength $thr_list]"
puts $sf "output_file=$output_file"
puts $sf "header_file=$header_file"
puts $sf "report_file=$report_file"
close $sf

if {![file exists $output_file]} {
  puts "ERROR: write_spice_deck completed but output file was not found: $output_file"
  exit 5
}

puts "DONE: wrote native SPICE deck $output_file"
exit
