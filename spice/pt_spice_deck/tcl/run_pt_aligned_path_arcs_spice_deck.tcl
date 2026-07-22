# Generate PrimeTime write_spice_deck -align_aggressors decks for every
# net arc listed in a path-stage CSV.
#
# Required environment variables:
#   TOP, VERILOG, SDC, SPEF, LIB_DB, CELL_SPF, MODEL_CARD, OUT_DIR, STAGE_CSV
#
# Optional:
#   EXTRA_LIBS, EXTRA_SPICE_INCLUDES, VDD, VSS
#   SWEEP_SIZE, SWEEP_STEP, SWEEP_EXHAUSTIVE, GROUND_COUPLING
#   ENABLE_SI_CORRELATION, INITIAL_DELAY_NS, MIN_TRAN_NS, TRAN_STEP_NS,
#   TRAN_SIZE_NS, LIMIT

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
  return [string trim [string map {"/" "_" "[" "_" "]" "_" ":" "_" " " "_" "\\" "_"} $text] "_"]
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
  puts $f "* PrimeTime native write_spice_deck aligned path-arc header"
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

proc csv_split {line} {
  # These generated stage CSVs have no quoted commas.
  return [split $line ","]
}

proc read_stage_csv {path} {
  set rows {}
  set f [open $path r]
  if {[gets $f header] < 0} {
    close $f
    return $rows
  }
  set columns [csv_split $header]
  while {[gets $f line] >= 0} {
    set line [string trim $line]
    if {$line eq ""} {
      continue
    }
    set values [csv_split $line]
    set row [dict create]
    for {set i 0} {$i < [llength $columns]} {incr i} {
      dict set row [lindex $columns $i] [lindex $values $i]
    }
    lappend rows $row
  }
  close $f
  return $rows
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
set STAGE_CSV  [env_required STAGE_CSV]

set EXTRA_LIBS             [env_default EXTRA_LIBS ""]
set EXTRA_SPICE_INCLUDES   [env_default EXTRA_SPICE_INCLUDES ""]
set VDD                    [env_default VDD 0.8]
set VSS                    [env_default VSS 0.0]
set SWEEP_SIZE             [env_default SWEEP_SIZE 3]
set SWEEP_STEP             [env_default SWEEP_STEP 0.01]
set SWEEP_EXHAUSTIVE       [bool_env SWEEP_EXHAUSTIVE false]
set GROUND_COUPLING        [bool_env GROUND_COUPLING false]
set ENABLE_SI_CORRELATION  [bool_env ENABLE_SI_CORRELATION true]
# Attempt to drive the true path input pin by passing the CELL arc (cell_from->
# cell_to) to write_spice_deck instead of the net arc. KNOWN BROKEN: write_spice_deck
# -align_aggressors needs a NET arc (a victim net with aggressors); a CELL arc has
# no alignable victim net, so it emits an EMPTY deck for most stages (56/76 on
# path1868). Only stages whose driver output net is treated as victim survive (~20).
# Default OFF to preserve the working net-arc flow. The correct fix needs a
# different mechanism (e.g. a get_timing_paths object write_spice_deck stitches,
# or post-processing the net-arc deck to switch the driven pin). See ledger 8-8.
set DRIVE_PATH_INPUT_PIN   [bool_env DRIVE_PATH_INPUT_PIN false]
set INITIAL_DELAY_NS       [env_default INITIAL_DELAY_NS 1.0]
set MIN_TRAN_NS            [env_default MIN_TRAN_NS 0.001]
set TRAN_STEP_NS           [env_default TRAN_STEP_NS 0.001]
set TRAN_SIZE_NS           [env_default TRAN_SIZE_NS 3.0]
set LIMIT                  [env_default LIMIT ""]

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
  [list MODEL_CARD $MODEL_CARD] \
  [list STAGE_CSV $STAGE_CSV]] {
  ensure_file [lindex $pair 0] [lindex $pair 1]
}
foreach include_file $EXTRA_SPICE_INCLUDE_LIST {
  ensure_file EXTRA_SPICE_INCLUDE $include_file
}

file mkdir $OUT_DIR
set header_file [file join $OUT_DIR "pt_aligned_path_arc_header.sp"]
write_header_file $header_file $MODEL_CARD $EXTRA_SPICE_INCLUDE_LIST $VDD $VSS

puts "INFO: TOP=$TOP"
puts "INFO: STAGE_CSV=$STAGE_CSV"
puts "INFO: OUT_DIR=$OUT_DIR"
puts "INFO: ENABLE_SI_CORRELATION=$ENABLE_SI_CORRELATION"

set stage_rows [read_stage_csv $STAGE_CSV]
puts "INFO: read [llength $stage_rows] stage rows"

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
  set seen_nets {}
  foreach row $stage_rows {
    if {![dict exists $row victim_net]} {
      continue
    }
    set victim_net [dict get $row victim_net]
    if {$victim_net eq "" || [lsearch -exact $seen_nets $victim_net] >= 0} {
      continue
    }
    lappend seen_nets $victim_net
    set corr_net_obj [get_nets -quiet $victim_net]
    if {[sizeof_collection $corr_net_obj] == 0} {
      puts "WARN: cannot enable SI correlation; victim net not found: $victim_net"
    } elseif {[catch {sim_enable_si_correlation $corr_net_obj} corr_msg]} {
      puts "WARN: sim_enable_si_correlation failed on $victim_net: $corr_msg"
    } else {
      puts "INFO: sim_enable_si_correlation enabled on $victim_net"
    }
  }
}

puts "INFO: update_timing with SI enabled"
if {[catch {update_timing -full} update_msg]} {
  puts "WARN: update_timing -full failed; retrying update_timing: $update_msg"
  update_timing
}

set manifest_file [file join $OUT_DIR "pt_stage_arc_generation.csv"]
set mf [open $manifest_file w]
puts $mf "stage_idx,analysis_type,cell_from,cell_to,net_from,net_to,stage_from,stage_to,victim_net,stage_dir,deck_basename,deck_file,status,message,arc_count,selected_arc"

set processed 0
foreach row $stage_rows {
  if {$LIMIT ne "" && $processed >= $LIMIT} {
    break
  }
  incr processed

  set stage_idx [dict get $row stage_idx]
  set analysis_type [dict get $row analysis_type]
  set cell_from [dict get $row cell_from]
  set cell_to [dict get $row cell_to]
  set net_from [dict get $row net_from]
  set net_to [dict get $row net_to]
  set stage_from [dict get $row stage_from]
  set stage_to [dict get $row stage_to]
  set victim_net [dict get $row victim_net]

  set stage_dir [file join $OUT_DIR [format "stage_%02d" $stage_idx]]
  file mkdir $stage_dir
  set deck_basename [format "path1856_stage%02d_%s_%s_align" $stage_idx [safe_name $victim_net] $analysis_type]
  set output_file [file join $stage_dir "${deck_basename}.sp"]
  set summary_file [file join $stage_dir "pt_aligned_arc_summary.txt"]

  puts "INFO: stage $stage_idx $net_from -> $net_to $analysis_type victim=$victim_net"

  set arc_from_obj [get_pins -quiet $net_from]
  set arc_to_obj   [get_pins -quiet $net_to]
  if {[sizeof_collection $arc_from_obj] == 0} {
    puts $mf "$stage_idx,$analysis_type,$cell_from,$cell_to,$net_from,$net_to,$stage_from,$stage_to,$victim_net,$stage_dir,$deck_basename,$output_file,FAIL,from_pin_not_found,0,"
    continue
  }
  if {[sizeof_collection $arc_to_obj] == 0} {
    puts $mf "$stage_idx,$analysis_type,$cell_from,$cell_to,$net_from,$net_to,$stage_from,$stage_to,$victim_net,$stage_dir,$deck_basename,$output_file,FAIL,to_pin_not_found,0,"
    continue
  }

  set arc_coll [get_timing_arcs -quiet -from $arc_from_obj -to $arc_to_obj]
  set timing_arc ""
  if {[sizeof_collection $arc_coll] > 0} {
    set timing_arc [index_collection $arc_coll 0]
  } else {
    set victim_net_obj [get_nets -quiet $victim_net]
    if {[sizeof_collection $victim_net_obj] > 0} {
      set arc_coll [get_timing_arcs -quiet -of_object $victim_net_obj]
      foreach_in_collection cand_arc $arc_coll {
        set cand_from [attr_or_na $cand_arc from_pin]
        set cand_to   [attr_or_na $cand_arc to_pin]
        if {$cand_from eq "NA" || $cand_to eq "NA"} {
          continue
        }
        set cand_from_name [object_full_name $cand_from]
        set cand_to_name   [object_full_name $cand_to]
        if {$cand_from_name eq $net_from && $cand_to_name eq $net_to} {
          set timing_arc $cand_arc
          break
        }
      }
    }
  }
  if {$timing_arc eq ""} {
    puts $mf "$stage_idx,$analysis_type,$cell_from,$cell_to,$net_from,$net_to,$stage_from,$stage_to,$victim_net,$stage_dir,$deck_basename,$output_file,FAIL,arc_not_found,[sizeof_collection $arc_coll],"
    continue
  }

  # Prepend the path cell arc (cell_from -> cell_to) so write_spice_deck drives
  # the true path input pin. Falls back to net-arc-only if the cell arc is not
  # resolvable, preserving the previous behavior.
  set spice_arc $timing_arc
  set drive_pin_mode "net_arc_only"
  if {$DRIVE_PATH_INPUT_PIN && $cell_from ne "" && $cell_to ne ""} {
    set cf [get_pins -quiet $cell_from]
    set ct [get_pins -quiet $cell_to]
    if {[sizeof_collection $cf] > 0 && [sizeof_collection $ct] > 0} {
      set cell_arc_coll [get_timing_arcs -quiet -from $cf -to $ct]
      if {[sizeof_collection $cell_arc_coll] > 0} {
        # Pass the CELL arc alone (single coherent arc). write_spice_deck then
        # drives the true path pin (A2) and emits the driven cell + its output
        # net + coupling for -align_aggressors. Combining cell+net arcs is WRONG:
        # write_spice_deck places them on independent time references (trig/targ
        # td mismatch) and the stage measure fails. Single arc keeps timing coherent.
        set spice_arc [index_collection $cell_arc_coll 0]
        set drive_pin_mode "path_cell_arc:$cell_from"
      } else {
        set drive_pin_mode "cell_arc_not_found:$cell_from->$cell_to"
      }
    }
  }
  puts "INFO: stage $stage_idx drive_pin=$drive_pin_mode"

  write_report [file join $stage_dir "arc_collection_attrs.rpt"] {
    puts "### get_timing_arcs -from $net_from -to $net_to"
    dump_arc_attrs $arc_coll
  }
  write_report [file join $stage_dir "arc_delay_calculation_crosstalk.rpt"] {
    puts "### report_delay_calculation -crosstalk victim arc"
    puts "### STAGE=$stage_idx VICTIM_NET=$victim_net FROM=$net_from TO=$net_to ANALYSIS_TYPE=$analysis_type"
    report_delay_calculation -max -crosstalk -from $net_from -to $net_to -nosplit
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
    -analysis_type $analysis_type]

  if {$GROUND_COUPLING} {
    lappend spice_cmd -ground_coupling_capacitors
  }
  lappend spice_cmd -align_aggressors
  if {[string trim $SWEEP_SIZE] ne "" && $SWEEP_SIZE ne "0"} {
    lappend spice_cmd -sweep_size $SWEEP_SIZE
  }
  if {[string trim $SWEEP_STEP] ne "" && $SWEEP_STEP ne "0"} {
    lappend spice_cmd -sweep_step $SWEEP_STEP
  }
  if {$SWEEP_EXHAUSTIVE} {
    lappend spice_cmd -sweep_exhaustive
  }
  lappend spice_cmd $spice_arc

  set status "UNKNOWN"
  set message ""
  if {[catch {set status [eval $spice_cmd]} message]} {
    puts "WARN: write_spice_deck failed for stage $stage_idx: $message"
    puts $mf "$stage_idx,$analysis_type,$cell_from,$cell_to,$net_from,$net_to,$stage_from,$stage_to,$victim_net,$stage_dir,$deck_basename,$output_file,FAIL,$message,[sizeof_collection $arc_coll],[get_object_name $timing_arc]"
    continue
  }

  set sf [open $summary_file "w"]
  puts $sf "status=$status"
  puts $sf "drive_pin_mode=$drive_pin_mode"
  puts $sf "stage_idx=$stage_idx"
  puts $sf "victim_net=$victim_net"
  puts $sf "cell_from=$cell_from"
  puts $sf "cell_to=$cell_to"
  puts $sf "net_from=$net_from"
  puts $sf "net_to=$net_to"
  puts $sf "stage_from=$stage_from"
  puts $sf "stage_to=$stage_to"
  puts $sf "analysis_type=$analysis_type"
  puts $sf "align_aggressors=true"
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

  if {[file exists $output_file]} {
    puts $mf "$stage_idx,$analysis_type,$cell_from,$cell_to,$net_from,$net_to,$stage_from,$stage_to,$victim_net,$stage_dir,$deck_basename,$output_file,PASS,$status,[sizeof_collection $arc_coll],[get_object_name $timing_arc]"
  } else {
    puts $mf "$stage_idx,$analysis_type,$cell_from,$cell_to,$net_from,$net_to,$stage_from,$stage_to,$victim_net,$stage_dir,$deck_basename,$output_file,FAIL,deck_missing,[sizeof_collection $arc_coll],[get_object_name $timing_arc]"
  }
}

close $mf
puts "DONE: wrote stage arc manifest $manifest_file"
exit
