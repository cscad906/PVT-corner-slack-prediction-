# PrimeTime SI aligned-aggressor arc deck flow.
#
# This script is intentionally arc-based, not path-based. PrimeTime
# write_spice_deck -align_aggressors applies to timing arcs returned by
# get_timing_arcs, so use this when debugging one victim net arc's
# crosstalk worst-case behavior.
#
# Required environment variables:
#   TOP        Top design name, e.g. BoomCore
#   VERILOG    Gate-level Verilog netlist
#   SDC        Timing constraints
#   SPEF       Parasitics for this RC corner
#   LIB_DB     PrimeTime .db timing library
#   CELL_SPF   SPICE/CDL file containing stdcell .SUBCKT definitions
#   MODEL_CARD Transistor modelcard to include in generated deck header
#   OUT_DIR    Output directory
#
# Optional environment variables:
#   EXTRA_LIBS             Additional .db files for link_path
#   EXTRA_SPICE_INCLUDES   Space-separated SPICE include files added to deck header
#   ARC_FROM_PIN           Victim arc source pin, default U32218/X
#   ARC_TO_PIN             Victim arc sink pin, default U32047/B
#   VICTIM_NET             Label for reports, default n38062
#   ANALYSIS_TYPE          max_rise|max_fall|min_rise|min_fall, default max_rise
#   ALIGN_AGGRESSORS       Use -align_aggressors, default true
#   SWEEP_SIZE             Optional write_spice_deck -sweep_size, default 3
#   SWEEP_STEP             Optional write_spice_deck -sweep_step in ns, default 0.01
#   SWEEP_EXHAUSTIVE       Optional -sweep_exhaustive, default false
#   GROUND_COUPLING        Optional -ground_coupling_capacitors, default false
#   ENABLE_SI_CORRELATION  Run sim_enable_si_correlation on VICTIM_NET, default true
#   VDD                    Logic one voltage, default 0.8
#   VSS                    Logic zero voltage, default 0.0
#   INITIAL_DELAY_NS       Initial PWL delay in ns, default 1.0
#   MIN_TRAN_NS            Minimum PWL transition in ns, default 0.001
#   TRAN_STEP_NS           SPICE .tran step in ns, default 0.001
#   TRAN_SIZE_NS           SPICE .tran stop time in ns, default 3.0
#   OUTPUT_BASENAME        Deck basename without extension, default arc_<net>_<type>

proc env_required {name} {
  if {![info exists ::env($name)] || $::env($name) eq ""} {
    puts "ERROR: required env var $name is empty"
    exit 2
  }
  return $::env($name)
}

proc env_default {name default_value} {
  if {![info exists ::env($name)] || $::env($name) eq ""} {
    return $default_value
  }
  return $::env($name)
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

proc safe_name {text} {
  return [string trim [string map {"/" "_" "[" "_" "]" "_" ":" "_" " " "_"} $text] "_"]
}

proc safe_set_app_var {name value} {
  if {[catch {set_app_var $name $value} msg]} {
    puts "WARN: could not set app var $name=$value: $msg"
  } else {
    puts "INFO: set_app_var $name $value"
  }
}

proc attr_or_na {obj attr} {
  if {[catch {get_attribute $obj $attr} value]} {
    return "NA"
  }
  return $value
}

proc object_full_name {obj} {
  if {[catch {get_attribute $obj full_name} value] || $value eq ""} {
    if {[catch {get_object_name $obj} value]} {
      return "NA"
    }
  }
  return $value
}

proc write_report {path body} {
  if {[catch {
    uplevel 1 [list redirect $path $body]
  } msg]} {
    set f [open $path w]
    puts $f "REPORT_FAILED: $msg"
    close $f
    puts "WARN: report failed for $path: $msg"
  } else {
    puts "INFO: wrote $path"
  }
}

proc write_header_file {header_file model_card extra_spice_includes vdd_value vss_value} {
  set f [open $header_file "w"]
  puts $f "* PrimeTime native write_spice_deck aligned arc header"
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

proc dump_arc_attrs {arc_coll} {
  set idx 0
  foreach_in_collection arc $arc_coll {
    incr idx
    puts "### ARC $idx [get_object_name $arc]"
    foreach attr {
      object_class
      from_pin
      to_pin
      from_object
      to_object
      is_net_arc
      is_cell_arc
      sense
      edge_type
      timing_sense
      delay_max_rise
      delay_max_fall
      annotated_delay_delta_max_rise
      annotated_delay_delta_max_fall
      annotated_rise_transition_delta_max
      annotated_fall_transition_delta_max
      annotated_delay_delta
      annotated_delta_transition
    } {
      puts [format "  %-30s %s" $attr [attr_or_na $arc $attr]]
    }
  }
}

set TOP        [env_required TOP]
set VERILOG    [env_required VERILOG]
set SDC        [env_required SDC]
set SPEF       [env_required SPEF]
set LIB_DB     [env_required LIB_DB]
set CELL_SPF   [env_required CELL_SPF]
set MODEL_CARD [env_required MODEL_CARD]
set OUT_DIR    [env_required OUT_DIR]

set EXTRA_LIBS             [env_default EXTRA_LIBS ""]
set EXTRA_SPICE_INCLUDES   [env_default EXTRA_SPICE_INCLUDES ""]
set ARC_FROM_PIN           [env_default ARC_FROM_PIN U32218/X]
set ARC_TO_PIN             [env_default ARC_TO_PIN U32047/B]
set VICTIM_NET             [env_default VICTIM_NET n38062]
set ANALYSIS_TYPE          [env_default ANALYSIS_TYPE max_rise]
set ALIGN_AGGRESSORS       [bool_env ALIGN_AGGRESSORS true]
set SWEEP_SIZE             [env_default SWEEP_SIZE 3]
set SWEEP_STEP             [env_default SWEEP_STEP 0.01]
set SWEEP_EXHAUSTIVE       [bool_env SWEEP_EXHAUSTIVE false]
set GROUND_COUPLING        [bool_env GROUND_COUPLING false]
set ENABLE_SI_CORRELATION  [bool_env ENABLE_SI_CORRELATION true]
set VDD                    [env_default VDD 0.8]
set VSS                    [env_default VSS 0.0]
set INITIAL_DELAY_NS       [env_default INITIAL_DELAY_NS 1.0]
set MIN_TRAN_NS            [env_default MIN_TRAN_NS 0.001]
set TRAN_STEP_NS           [env_default TRAN_STEP_NS 0.001]
set TRAN_SIZE_NS           [env_default TRAN_SIZE_NS 3.0]
set OUTPUT_BASENAME        [env_default OUTPUT_BASENAME ""]

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
  [list CELL_SPF $CELL_SPF] \
  [list MODEL_CARD $MODEL_CARD]] {
  ensure_file [lindex $pair 0] [lindex $pair 1]
}
foreach include_file $EXTRA_SPICE_INCLUDE_LIST {
  ensure_file EXTRA_SPICE_INCLUDE $include_file
}

file mkdir $OUT_DIR
if {$OUTPUT_BASENAME eq ""} {
  set OUTPUT_BASENAME "arc_[safe_name $VICTIM_NET]_${ANALYSIS_TYPE}"
}
set header_file  [file join $OUT_DIR "pt_aligned_arc_header.sp"]
set output_file  [file join $OUT_DIR "${OUTPUT_BASENAME}.sp"]
set summary_file [file join $OUT_DIR "pt_aligned_arc_summary.txt"]
write_header_file $header_file $MODEL_CARD $EXTRA_SPICE_INCLUDE_LIST $VDD $VSS

puts "INFO: TOP=$TOP"
puts "INFO: VERILOG=$VERILOG"
puts "INFO: SDC=$SDC"
puts "INFO: SPEF=$SPEF"
puts "INFO: LIB_DB=$LIB_DB"
puts "INFO: CELL_SPF=$CELL_SPF"
puts "INFO: EXTRA_SPICE_INCLUDES=$EXTRA_SPICE_INCLUDES"
puts "INFO: OUT_DIR=$OUT_DIR"
puts "INFO: ARC_FROM_PIN=$ARC_FROM_PIN"
puts "INFO: ARC_TO_PIN=$ARC_TO_PIN"
puts "INFO: VICTIM_NET=$VICTIM_NET"
puts "INFO: ANALYSIS_TYPE=$ANALYSIS_TYPE ALIGN_AGGRESSORS=$ALIGN_AGGRESSORS SWEEP_SIZE=$SWEEP_SIZE SWEEP_STEP=$SWEEP_STEP"
puts "INFO: ENABLE_SI_CORRELATION=$ENABLE_SI_CORRELATION"

set search_path [list . [file dirname $VERILOG] [file dirname $LIB_DB]]
set target_library [list $LIB_DB]
if {$EXTRA_LIBS ne ""} {
  set link_path "* $LIB_DB $EXTRA_LIBS"
} else {
  set link_path "* $LIB_DB"
}

safe_set_app_var si_enable_analysis true
safe_set_app_var timing_disable_cond_default_arcs true
safe_set_app_var timing_report_use_worst_parallel_cell_arc false
safe_set_app_var delay_calc_waveform_analysis_mode full_design
safe_set_app_var timing_keep_waveform_on_points true
safe_set_app_var timing_save_pin_arrival_and_slack true

read_verilog $VERILOG
current_design $TOP
link_design
read_sdc $SDC
read_parasitics -keep_capacitive_coupling $SPEF
set_propagated_clock [all_clocks]

if {$ENABLE_SI_CORRELATION} {
  set corr_net_obj [get_nets -quiet $VICTIM_NET]
  if {[sizeof_collection $corr_net_obj] == 0} {
    puts "WARN: cannot enable SI correlation; VICTIM_NET not found: $VICTIM_NET"
  } elseif {[catch {sim_enable_si_correlation $corr_net_obj} corr_msg]} {
    puts "WARN: sim_enable_si_correlation failed on $VICTIM_NET: $corr_msg"
  } else {
    puts "INFO: sim_enable_si_correlation enabled on $VICTIM_NET"
  }
}

puts "INFO: update_timing with SI enabled"
if {[catch {update_timing -full} update_msg]} {
  puts "WARN: update_timing -full failed; retrying update_timing: $update_msg"
  update_timing
}

set arc_from_obj [get_pins -quiet $ARC_FROM_PIN]
set arc_to_obj   [get_pins -quiet $ARC_TO_PIN]
if {[sizeof_collection $arc_from_obj] == 0} {
  puts "ERROR: ARC_FROM_PIN not found: $ARC_FROM_PIN"
  exit 3
}
if {[sizeof_collection $arc_to_obj] == 0} {
  puts "ERROR: ARC_TO_PIN not found: $ARC_TO_PIN"
  exit 3
}

set arc_coll [get_timing_arcs -quiet -from $arc_from_obj -to $arc_to_obj]
set timing_arc ""
if {[sizeof_collection $arc_coll] > 0} {
  set timing_arc [index_collection $arc_coll 0]
  if {[sizeof_collection $arc_coll] > 1} {
    puts "WARN: get_timing_arcs -from/-to returned [sizeof_collection $arc_coll] arcs; using first arc [get_object_name $timing_arc]"
  } else {
    puts "INFO: using timing arc [get_object_name $timing_arc]"
  }
} else {
  puts "WARN: get_timing_arcs -from/-to returned no arc; retrying from victim net $VICTIM_NET"
  set victim_net_obj [get_nets -quiet $VICTIM_NET]
  if {[sizeof_collection $victim_net_obj] == 0} {
    puts "ERROR: VICTIM_NET not found: $VICTIM_NET"
    exit 4
  }
  set arc_coll [get_timing_arcs -quiet -of_object $victim_net_obj]
  foreach_in_collection cand_arc $arc_coll {
    set cand_from [attr_or_na $cand_arc from_pin]
    set cand_to   [attr_or_na $cand_arc to_pin]
    if {$cand_from eq "NA" || $cand_to eq "NA"} {
      continue
    }
    set cand_from_name [object_full_name $cand_from]
    set cand_to_name   [object_full_name $cand_to]
    if {$cand_from_name eq $ARC_FROM_PIN && $cand_to_name eq $ARC_TO_PIN} {
      set timing_arc $cand_arc
      break
    }
  }
  if {$timing_arc eq ""} {
    puts "ERROR: no net timing arc matched $ARC_FROM_PIN -> $ARC_TO_PIN on $VICTIM_NET"
    exit 4
  }
  puts "INFO: using victim-net timing arc [get_object_name $timing_arc]"
}

write_report [file join $OUT_DIR "arc_collection_attrs.rpt"] {
  puts "### get_timing_arcs -from $ARC_FROM_PIN -to $ARC_TO_PIN"
  dump_arc_attrs $arc_coll
}

write_report [file join $OUT_DIR "arc_delay_calculation_crosstalk.rpt"] {
  puts "### report_delay_calculation -crosstalk victim arc"
  puts "### VICTIM_NET=$VICTIM_NET FROM=$ARC_FROM_PIN TO=$ARC_TO_PIN ANALYSIS_TYPE=$ANALYSIS_TYPE"
  report_delay_calculation -max -crosstalk -from $ARC_FROM_PIN -to $ARC_TO_PIN -nosplit
}

write_report [file join $OUT_DIR "arc_timing_through_victim.rpt"] {
  puts "### report_timing through victim arc pins"
  report_timing \
    -delay_type max \
    -through $arc_from_obj \
    -through $arc_to_obj \
    -max_paths 10 \
    -nworst 10 \
    -sort_by slack \
    -input_pins \
    -nets \
    -capacitance \
    -transition_time \
    -crosstalk_delta \
    -nosplit \
    -significant_digits 6
}

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
  -sub_circuit_file $CELL_SPF \
  -analysis_type $ANALYSIS_TYPE]

if {$GROUND_COUPLING} {
  lappend spice_cmd -ground_coupling_capacitors
}
if {$ALIGN_AGGRESSORS} {
  lappend spice_cmd -align_aggressors
}
if {[string trim $SWEEP_SIZE] ne "" && $SWEEP_SIZE ne "0"} {
  lappend spice_cmd -sweep_size $SWEEP_SIZE
}
if {[string trim $SWEEP_STEP] ne "" && $SWEEP_STEP ne "0"} {
  lappend spice_cmd -sweep_step $SWEEP_STEP
}
if {$SWEEP_EXHAUSTIVE} {
  lappend spice_cmd -sweep_exhaustive
}
lappend spice_cmd $timing_arc

puts "INFO: running write_spice_deck -> $output_file"
set status [eval $spice_cmd]
puts "INFO: write_spice_deck status=$status"

set sf [open $summary_file "w"]
puts $sf "status=$status"
puts $sf "top=$TOP"
puts $sf "victim_net=$VICTIM_NET"
puts $sf "arc_from_pin=$ARC_FROM_PIN"
puts $sf "arc_to_pin=$ARC_TO_PIN"
puts $sf "analysis_type=$ANALYSIS_TYPE"
puts $sf "align_aggressors=$ALIGN_AGGRESSORS"
puts $sf "sweep_size=$SWEEP_SIZE"
puts $sf "sweep_step=$SWEEP_STEP"
puts $sf "sweep_exhaustive=$SWEEP_EXHAUSTIVE"
puts $sf "ground_coupling=$GROUND_COUPLING"
puts $sf "enable_si_correlation=$ENABLE_SI_CORRELATION"
puts $sf "vdd=$VDD"
puts $sf "vss=$VSS"
puts $sf "initial_delay_ns=$INITIAL_DELAY_NS"
puts $sf "minimum_transition_ns=$MIN_TRAN_NS"
puts $sf "transient_step_ns=$TRAN_STEP_NS"
puts $sf "transient_size_ns=$TRAN_SIZE_NS"
puts $sf "output_file=$output_file"
puts $sf "header_file=$header_file"
puts $sf "arc_count=[sizeof_collection $arc_coll]"
puts $sf "selected_arc=[get_object_name $timing_arc]"
close $sf

if {![file exists $output_file]} {
  puts "ERROR: write_spice_deck completed but output file was not found: $output_file"
  exit 5
}

puts "DONE: wrote aligned-aggressor arc SPICE deck $output_file"
exit
