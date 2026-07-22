# Input resolution: explicit Tcl var (pt_shell -x "set VAR ...") first,
# then environment variable, then default. Required inputs error out if
# neither is provided.
proc env_or {name {fallback ""}} {
  if {[info exists ::env($name)] && $::env($name) ne ""} { return $::env($name) }
  return $fallback
}
set SCRIPT_DIR [file dirname [file normalize [info script]]]

if {![info exists TOP]} {
  set TOP [env_or XTALK_TOP "BoomCore"]
}
if {![info exists VERILOG]} {
  set VERILOG [env_or XTALK_VERILOG]
}
if {![info exists SDC]} {
  set SDC [env_or XTALK_SDC]
}
if {![info exists SPEF]} {
  set SPEF [env_or XTALK_SPEF]
}
if {![info exists DB_DIR]} {
  set DB_DIR [env_or XTALK_DB_DIR]
}
if {![info exists ANALYSIS]} {
  set ANALYSIS [env_or XTALK_OUT_DIR [pwd]]
}
foreach _req {VERILOG SDC SPEF DB_DIR} {
  if {[set $_req] eq ""} {
    error "required input $_req not set (set Tcl var $_req or env XTALK_$_req)"
  }
}

if {![info exists ACTIVE_OUT]} {
  set ACTIVE_OUT "$ANALYSIS/voltage_active_aggressor_path1"
}
if {![info exists WINDOW_OUT]} {
  set WINDOW_OUT "$ANALYSIS/timing_windows_by_voltage_from_union"
}
if {![info exists REQUESTED_OUT]} {
  set REQUESTED_OUT "$ANALYSIS/requested_si_features_path1"
}

# Target fixed path: start/end register instances (site/design specific).
if {![info exists START_CELL]} {
  set START_CELL [env_or XTALK_START_CELL "iregister_read_exe_reg_rs1_data_1_reg_1_"]
}
if {![info exists END_CELL]} {
  set END_CELL [env_or XTALK_END_CELL "iregister_read_exe_reg_rs2_data_1_reg_63_"]
}

if {![info exists RUN_ACTIVE_PARSERS]} {
  set RUN_ACTIVE_PARSERS 1
}
if {![info exists RUN_FINAL_TABLES]} {
  set RUN_FINAL_TABLES 1
}
# Python interpreter for the embedded parser steps (needs 3.9+).
if {![info exists PYTHON_BIN]} {
  set PYTHON_BIN [env_or XTALK_PYTHON "python3"]
}
# Parsers live next to this script by default.
if {![info exists PARSE_SCRIPT]} {
  set PARSE_SCRIPT "$SCRIPT_DIR/parsers/parse_voltage_active_aggressors.py"
}
if {![info exists EXPORT_SCRIPT]} {
  set EXPORT_SCRIPT "$SCRIPT_DIR/parsers/export_active_aggressors_by_corner.py"
}
if {![info exists FINAL_TABLE_SCRIPT]} {
  set FINAL_TABLE_SCRIPT "$SCRIPT_DIR/parsers/make_requested_si_feature_tables.py"
}

if {![info exists VOLTAGES]} {
  set VOLTAGES {
    {0.600 0p6}
    {0.605 0p605}
    {0.610 0p610}
    {0.615 0p615}
    {0.620 0p620}
    {0.625 0p625}
    {0.650 0p65}
    {0.675 0p675}
    {0.700 0p7}
    {0.725 0p725}
    {0.750 0p75}
    {0.775 0p775}
    {0.780 0p780}
    {0.785 0p785}
    {0.790 0p790}
    {0.795 0p795}
    {0.800 0p8}
  }
}

proc sanitize {s} {
  return [string map {"\t" " " "\n" " " "\r" " "} $s]
}

proc safe_name {s} {
  return [string map {"/" "_" "[" "_" "]" "_" ":" "_" " " "_" "\\" "_"} $s]
}

proc attr_or_empty {obj attr} {
  if {$obj eq ""} {
    return ""
  }
  set rc [catch {get_attribute $obj $attr} val]
  if {$rc != 0} {
    return ""
  }
  return [sanitize $val]
}

proc numeric_min {values} {
  set seen 0
  set best 0.0
  foreach val $values {
    if {$val eq ""} {
      continue
    }
    if {!$seen || $val < $best} {
      set best $val
      set seen 1
    }
  }
  if {!$seen} {
    return ""
  }
  return $best
}

proc numeric_max {values} {
  set seen 0
  set best 0.0
  foreach val $values {
    if {$val eq ""} {
      continue
    }
    if {!$seen || $val > $best} {
      set best $val
      set seen 1
    }
  }
  if {!$seen} {
    return ""
  }
  return $best
}

proc window_string {lo hi} {
  if {$lo eq "" || $hi eq ""} {
    return ""
  }
  return "\[$lo, $hi\]"
}

proc overlap_width {a_min a_max b_min b_max} {
  if {$a_min eq "" || $a_max eq "" || $b_min eq "" || $b_max eq ""} {
    return ""
  }
  set s $a_min
  if {$b_min > $s} {
    set s $b_min
  }
  set e $a_max
  if {$b_max < $e} {
    set e $b_max
  }
  set w [expr {$e - $s}]
  if {$w < 0} {
    return "0"
  }
  return $w
}

proc overlap_flag {width} {
  if {$width eq ""} {
    return ""
  }
  if {$width > 0} {
    return "Y"
  }
  return "N"
}

proc pin_cell_name {pin_name} {
  set idx [string last "/" $pin_name]
  if {$idx < 0} {
    return ""
  }
  return [string range $pin_name 0 [expr {$idx - 1}]]
}

proc first_net_name {pin_obj} {
  set nets [get_nets -quiet -of_objects $pin_obj]
  if {[sizeof_collection $nets] == 0} {
    return ""
  }
  return [get_object_name [index_collection $nets 0]]
}

proc first_driver_pin {net_name} {
  set net [get_nets -quiet $net_name]
  if {[sizeof_collection $net] == 0} {
    return ""
  }
  set pins [get_pins -quiet -of_objects $net -filter "direction == out || direction == inout"]
  if {[sizeof_collection $pins] == 0} {
    return ""
  }
  return [get_object_name [index_collection $pins 0]]
}

proc all_driver_pins {net_name} {
  set net [get_nets -quiet $net_name]
  if {[sizeof_collection $net] == 0} {
    return ""
  }
  set pins [get_pins -quiet -of_objects $net -filter "direction == out || direction == inout"]
  if {[sizeof_collection $pins] == 0} {
    return ""
  }
  return [join [get_object_name $pins] ";"]
}

proc all_load_pins {net_name} {
  set net [get_nets -quiet $net_name]
  if {[sizeof_collection $net] == 0} {
    return ""
  }
  set pins [get_pins -quiet -of_objects $net -filter "direction == in || direction == inout"]
  if {[sizeof_collection $pins] == 0} {
    return ""
  }
  return [join [get_object_name $pins] ";"]
}

proc window_for_pin {pin_name} {
  if {$pin_name eq ""} {
    return [dict create pin "" arrival_window "" min_rise "" max_rise "" min_fall "" max_fall "" overall_min "" overall_max "" actual_rise_transition_max "" actual_fall_transition_max "" slew_max "" status "NO_PIN"]
  }
  set pin [get_pins -quiet $pin_name]
  if {[sizeof_collection $pin] == 0} {
    return [dict create pin $pin_name arrival_window "" min_rise "" max_rise "" min_fall "" max_fall "" overall_min "" overall_max "" actual_rise_transition_max "" actual_fall_transition_max "" slew_max "" status "PIN_NOT_FOUND"]
  }
  set min_rise [attr_or_empty $pin min_rise_arrival]
  set max_rise [attr_or_empty $pin max_rise_arrival]
  set min_fall [attr_or_empty $pin min_fall_arrival]
  set max_fall [attr_or_empty $pin max_fall_arrival]
  set actual_rise_transition_max [attr_or_empty $pin actual_rise_transition_max]
  set actual_fall_transition_max [attr_or_empty $pin actual_fall_transition_max]
  set slew_max [numeric_max [list $actual_rise_transition_max $actual_fall_transition_max]]
  set overall_min [numeric_min [list $min_rise $min_fall]]
  set overall_max [numeric_max [list $max_rise $max_fall]]
  return [dict create \
    pin $pin_name \
    arrival_window [attr_or_empty $pin arrival_window] \
    min_rise $min_rise \
    max_rise $max_rise \
    min_fall $min_fall \
    max_fall $max_fall \
    overall_min $overall_min \
    overall_max $overall_max \
    actual_rise_transition_max $actual_rise_transition_max \
    actual_fall_transition_max $actual_fall_transition_max \
    slew_max $slew_max \
    status "OK"]
}

proc window_for_net_driver {net_name} {
  set driver_pin [first_driver_pin $net_name]
  if {$driver_pin eq ""} {
    return [dict create driver_pin "" all_driver_pins "" load_pins "" arrival_window "" min_rise "" max_rise "" min_fall "" max_fall "" overall_min "" overall_max "" actual_rise_transition_max "" actual_fall_transition_max "" slew_max "" status "NO_DRIVER"]
  }
  set pdata [window_for_pin $driver_pin]
  return [dict create \
    driver_pin $driver_pin \
    all_driver_pins [all_driver_pins $net_name] \
    load_pins [all_load_pins $net_name] \
    arrival_window [dict get $pdata arrival_window] \
    min_rise [dict get $pdata min_rise] \
    max_rise [dict get $pdata max_rise] \
    min_fall [dict get $pdata min_fall] \
    max_fall [dict get $pdata max_fall] \
    overall_min [dict get $pdata overall_min] \
    overall_max [dict get $pdata overall_max] \
    actual_rise_transition_max [dict get $pdata actual_rise_transition_max] \
    actual_fall_transition_max [dict get $pdata actual_fall_transition_max] \
    slew_max [dict get $pdata slew_max] \
    status [dict get $pdata status]]
}

proc lib_db_for_voltage {db_dir voltage vtag} {
  global LIB_DB_BY_VTAG
  # Highest priority: explicit per-vtag db path.
  if {[array exists LIB_DB_BY_VTAG] && [info exists LIB_DB_BY_VTAG($vtag)]} {
    return $LIB_DB_BY_VTAG($vtag)
  }
  # Otherwise build the db stem from a format string ({vtag} -> voltage tag).
  # Default is the internal TT / 25C library; override the process prefix or
  # temperature via env XTALK_DB_STEM_FORMAT, e.g.
  #   setenv XTALK_DB_STEM_FORMAT "mylib_ss{vtag}v125c_ccs_..._mono"
  set fmt [env_or XTALK_DB_STEM_FORMAT "saed14rvt_tt{vtag}v25c_ccs_rth0p01_full385_3ns250fj_mono"]
  regsub -all {\{vtag\}} $fmt $vtag stem
  return "$db_dir/${stem}.db"
}

proc setup_design_for_voltage {top verilog sdc spef db_dir vtag} {
  set lib_db [lib_db_for_voltage $db_dir "" $vtag]
  set_app_var si_enable_analysis true
  set_app_var timing_save_pin_arrival_and_slack true
  read_verilog $verilog
  current_design $top
  set ::link_path "* $lib_db"
  link_design
  read_sdc $sdc
  read_parasitics -format spef -keep_capacitive_coupling $spef
  set_propagated_clock [all_clocks]
  update_timing
}

proc collect_fixed_path_arcs {start_cell end_cell point_file} {
  set result [dict create path_count 0 point_count 0 slack "NA" arrival "NA" required "NA" arcs [list]]
  set paths [get_timing_paths -delay_type max -from [get_cells $start_cell] -to [get_cells $end_cell] -max_paths 1]
  set path_count [sizeof_collection $paths]
  dict set result path_count $path_count
  if {$path_count == 0} {
    return $result
  }

  set path [index_collection $paths 0]
  set points [get_attribute $path points]
  dict set result point_count [sizeof_collection $points]
  dict set result slack [get_attribute $path slack]
  dict set result arrival [get_attribute $path arrival]
  dict set result required [get_attribute $path required]

  set pf [open $point_file w]
  puts $pf "idx\tpin\tdirection\tnet"

  set pin_names {}
  set pin_dirs {}
  set pin_nets {}
  set idx 0
  foreach_in_collection point $points {
    incr idx
    set obj [get_attribute $point object]
    set pin_name [get_object_name $obj]
    set dir [get_attribute $obj direction]
    set net_name [first_net_name $obj]
    lappend pin_names $pin_name
    lappend pin_dirs $dir
    lappend pin_nets $net_name
    puts $pf "$idx\t$pin_name\t$dir\t$net_name"
  }
  close $pf

  set arcs [list]
  set arc_idx 0
  for {set i 1} {$i < [llength $pin_names]} {incr i} {
    set from_pin [lindex $pin_names [expr {$i - 1}]]
    set to_pin [lindex $pin_names $i]
    set from_dir [lindex $pin_dirs [expr {$i - 1}]]
    set to_dir [lindex $pin_dirs $i]
    set from_net [lindex $pin_nets [expr {$i - 1}]]
    set to_net [lindex $pin_nets $i]

    if {$from_net eq "" || $to_net eq "" || $from_net ne $to_net} {
      continue
    }
    if {$from_dir ne "out" && $from_dir ne "inout"} {
      continue
    }
    if {$to_dir ne "in" && $to_dir ne "inout"} {
      continue
    }
    if {[pin_cell_name $from_pin] eq [pin_cell_name $to_pin]} {
      continue
    }

    incr arc_idx
    lappend arcs [dict create arc_idx $arc_idx victim_net $from_net from_pin $from_pin to_pin $to_pin]
  }
  dict set result arcs $arcs
  return $result
}

proc write_raw_si_attrs {fh voltage vtag victim} {
  set net [get_nets -quiet $victim]
  if {[sizeof_collection $net] == 0} {
    puts $fh "$voltage\t$vtag\t[sanitize $victim]\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\tNET_NOT_FOUND"
    return
  }
  set row [list \
    $voltage \
    $vtag \
    [sanitize $victim] \
    [attr_or_empty $net annotated_delay_delta_max] \
    [attr_or_empty $net annotated_delay_delta_min] \
    [attr_or_empty $net number_of_aggressors] \
    [attr_or_empty $net number_of_effective_aggressors] \
    [attr_or_empty $net total_coupling_capacitance] \
    [attr_or_empty $net total_effective_coupling_capacitance] \
    [attr_or_empty $net aggressors] \
    [attr_or_empty $net effective_aggressors] \
    [attr_or_empty $net coupling_capacitors] \
    [attr_or_empty $net effective_coupling_capacitors] \
    [attr_or_empty $net si_xtalk_bumps] \
    [attr_or_empty $net si_xtalk_bumps_max_rise] \
    [attr_or_empty $net si_xtalk_bumps_max_fall] \
    [attr_or_empty $net si_xtalk_bumps_min_rise] \
    [attr_or_empty $net si_xtalk_bumps_min_fall] \
    "OK"]
  puts $fh [join $row "\t"]
}

proc write_victim_load_window {fh voltage vtag arc} {
  set victim [dict get $arc victim_net]
  set to_pin [dict get $arc to_pin]
  set w [window_for_pin $to_pin]
  puts $fh "$voltage\t$vtag\t$victim\t$to_pin\t[dict get $w arrival_window]\t[dict get $w min_rise]\t[dict get $w max_rise]\t[dict get $w min_fall]\t[dict get $w max_fall]\t[dict get $w overall_min]\t[dict get $w overall_max]\t[dict get $w status]"
}

proc read_union_rows {union_file} {
  set rows {}
  set fh [open $union_file r]
  gets $fh header
  while {[gets $fh line] >= 0} {
    if {[string trim $line] eq ""} {
      continue
    }
    set fields [split $line "\t"]
    set victim [lindex $fields 0]
    set aggressors [lindex $fields 1]
    lappend rows [list $victim $aggressors]
  }
  close $fh
  return $rows
}

proc unique_nets_from_union {union_rows} {
  set unique_nets {}
  array set seen_net {}
  foreach row $union_rows {
    set victim [lindex $row 0]
    set aggressors [lindex $row 1]
    foreach net_name [concat [list $victim] [split $aggressors ";"]] {
      if {$net_name eq ""} {
        continue
      }
      if {![info exists seen_net($net_name)]} {
        set seen_net($net_name) 1
        lappend unique_nets $net_name
      }
    }
  }
  return $unique_nets
}

proc build_path_load_windows {start_cell end_cell} {
  array set result {}
  set tmp [collect_fixed_path_arcs $start_cell $end_cell "/dev/null"]
  foreach arc [dict get $tmp arcs] {
    set victim [dict get $arc victim_net]
    set from_pin [dict get $arc from_pin]
    set to_pin [dict get $arc to_pin]
    set result($victim) [dict create from_pin $from_pin to_pin $to_pin window [window_for_pin $to_pin]]
  }
  return [array get result]
}

file mkdir $ACTIVE_OUT
file mkdir $REQUESTED_OUT
file mkdir $WINDOW_OUT
file mkdir "$WINDOW_OUT/per_voltage"

set path_metric_file "$ACTIVE_OUT/path_metrics.tsv"
set arc_list_file "$ACTIVE_OUT/arc_reports.tsv"
set raw_attr_file "$REQUESTED_OUT/requested_si_attrs.raw_net_attrs.tsv"
set combined_victim_file "$WINDOW_OUT/all_voltages_victim_path_load_windows.tsv"

set pm [open $path_metric_file w]
puts $pm "voltage\tvtag\tpath_count\tpoint_count\tnet_arc_count\tslack\tarrival\trequired\tstartpoint\tendpoint"
close $pm

set af [open $arc_list_file w]
puts $af "voltage\tvtag\tarc_idx\tvictim_net\tfrom_pin\tto_pin\treport_file\tstatus\tmessage"
close $af

set rf [open $raw_attr_file w]
puts $rf "voltage\tvtag\tvictim_net\tannotated_delay_delta_max\tannotated_delay_delta_min\tnumber_of_aggressors\tnumber_of_effective_aggressors\ttotal_coupling_capacitance\ttotal_effective_coupling_capacitance\taggressors\teffective_aggressors\tcoupling_capacitors\teffective_coupling_capacitors\tsi_xtalk_bumps\tsi_xtalk_bumps_max_rise\tsi_xtalk_bumps_max_fall\tsi_xtalk_bumps_min_rise\tsi_xtalk_bumps_min_fall\tstatus"
close $rf

set cvf [open $combined_victim_file w]
puts $cvf "voltage\tvtag\tvictim_net\tvictim_load_pin\tarrival_window\tmin_rise\tmax_rise\tmin_fall\tmax_fall\toverall_min\toverall_max\tstatus"
close $cvf

foreach vinfo $VOLTAGES {
  set voltage [lindex $vinfo 0]
  set vtag [lindex $vinfo 1]
  set vout "$ACTIVE_OUT/$vtag"
  file mkdir $vout
  cd $vout

  puts "INFO: pass1 active reports and victim attrs for $voltage ($vtag)"
  setup_design_for_voltage $TOP $VERILOG $SDC $SPEF $DB_DIR $vtag

  set path_data [collect_fixed_path_arcs $START_CELL $END_CELL "$vout/path_points.tsv"]
  set arcs [dict get $path_data arcs]

  set pm [open $path_metric_file a]
  puts $pm "$voltage\t$vtag\t[dict get $path_data path_count]\t[dict get $path_data point_count]\t[llength $arcs]\t[dict get $path_data slack]\t[dict get $path_data arrival]\t[dict get $path_data required]\t$START_CELL\t$END_CELL"
  close $pm

  set af [open $arc_list_file a]
  set rf [open $raw_attr_file a]
  set cvf [open $combined_victim_file a]

  foreach arc $arcs {
    set arc_idx [dict get $arc arc_idx]
    set victim [dict get $arc victim_net]
    set from_pin [dict get $arc from_pin]
    set to_pin [dict get $arc to_pin]
    set from_obj [get_pins -quiet $from_pin]
    set to_obj [get_pins -quiet $to_pin]
    set report_file "$vout/report_delay_calculation.crosstalk.arc[format %03d $arc_idx].[safe_name $victim].[safe_name $to_pin].rpt"
    set status "OK"
    set message ""

    set rc [catch {
      redirect -file $report_file {
        puts "### VOLTAGE $voltage"
        puts "### PATH $START_CELL -> $END_CELL"
        puts "### ARC $arc_idx"
        puts "### VICTIM_NET $victim"
        puts "### FROM $from_pin"
        puts "### TO $to_pin"
        report_delay_calculation -crosstalk -from $from_obj -to $to_obj
      }
    } err]
    if {$rc != 0} {
      set status "ERROR"
      set message [string map {"\t" " " "\n" " "} $err]
    }
    puts $af "$voltage\t$vtag\t$arc_idx\t$victim\t$from_pin\t$to_pin\t$report_file\t$status\t$message"

    write_raw_si_attrs $rf $voltage $vtag $victim
    write_victim_load_window $cvf $voltage $vtag $arc
  }

  close $af
  close $rf
  close $cvf
  catch {remove_design -all}
}

if {$RUN_ACTIVE_PARSERS} {
  puts "INFO: parsing active aggressor reports"
  puts [exec $PYTHON_BIN $PARSE_SCRIPT $ACTIVE_OUT]
  puts [exec $PYTHON_BIN $EXPORT_SCRIPT $ACTIVE_OUT]
}

set union_file "$ACTIVE_OUT/active_only_by_corner/all_voltage_union.active_aggressor_names.tsv"
set union_rows [read_union_rows $union_file]
set unique_nets [unique_nets_from_union $union_rows]

set combined_pair_file "$WINDOW_OUT/all_voltages_victim_aggressor_timing_windows.simple.tsv"
set combined_net_file "$WINDOW_OUT/all_voltages_net_driver_timing_windows.tsv"

set cpf [open $combined_pair_file w]
puts $cpf "voltage\tvtag\tvictim_net\taggressor_net\tvictim_from_pin\tvictim_to_pin\tvictim_load_window\taggressor_driver_pin\taggressor_driver_window\toverlap_width\toverlap"
close $cpf

set cnf [open $combined_net_file w]
puts $cnf "voltage\tvtag\tnet\tdriver_pin\tall_driver_pins\tload_pins\tarrival_window\tmin_rise\tmax_rise\tmin_fall\tmax_fall\toverall_min\toverall_max\tactual_rise_transition_max\tactual_fall_transition_max\tslew_max\tstatus"
close $cnf

foreach vinfo $VOLTAGES {
  set voltage [lindex $vinfo 0]
  set vtag [lindex $vinfo 1]
  set vout "$WINDOW_OUT/per_voltage/$vtag"
  file mkdir $vout
  cd $vout

  puts "INFO: pass2 aggressor driver windows for $voltage ($vtag)"
  setup_design_for_voltage $TOP $VERILOG $SDC $SPEF $DB_DIR $vtag

  array set path_load [build_path_load_windows $START_CELL $END_CELL]
  array set win {}
  foreach net_name $unique_nets {
    set win($net_name) [window_for_net_driver $net_name]
  }

  set per_pair_file "$vout/${vtag}.victim_aggressor_timing_windows.simple.tsv"
  set ppf [open $per_pair_file w]
  puts $ppf "victim_net\taggressor_net\tvictim_from_pin\tvictim_to_pin\tvictim_load_window\taggressor_driver_pin\taggressor_driver_window\toverlap_width\toverlap"

  set cpf [open $combined_pair_file a]
  foreach row $union_rows {
    set victim [lindex $row 0]
    set aggressors [lindex $row 1]
    if {![info exists path_load($victim)]} {
      continue
    }
    set vrec $path_load($victim)
    set vwin [dict get $vrec window]
    set vmin [dict get $vwin overall_min]
    set vmax [dict get $vwin overall_max]
    set vwin_str [window_string $vmin $vmax]

    foreach aggressor [split $aggressors ";"] {
      if {$aggressor eq "" || ![info exists win($aggressor)]} {
        continue
      }
      set awin $win($aggressor)
      set amin [dict get $awin overall_min]
      set amax [dict get $awin overall_max]
      set awin_str [window_string $amin $amax]
      set width [overlap_width $vmin $vmax $amin $amax]
      set flag [overlap_flag $width]

      set line "$victim\t$aggressor\t[dict get $vrec from_pin]\t[dict get $vrec to_pin]\t$vwin_str\t[dict get $awin driver_pin]\t$awin_str\t$width\t$flag"
      puts $ppf $line
      puts $cpf "$voltage\t$vtag\t$line"
    }
  }
  close $cpf
  close $ppf

  set cnf [open $combined_net_file a]
  foreach net_name $unique_nets {
    set data $win($net_name)
    puts $cnf "$voltage\t$vtag\t$net_name\t[dict get $data driver_pin]\t[dict get $data all_driver_pins]\t[dict get $data load_pins]\t[dict get $data arrival_window]\t[dict get $data min_rise]\t[dict get $data max_rise]\t[dict get $data min_fall]\t[dict get $data max_fall]\t[dict get $data overall_min]\t[dict get $data overall_max]\t[dict get $data actual_rise_transition_max]\t[dict get $data actual_fall_transition_max]\t[dict get $data slew_max]\t[dict get $data status]"
  }
  close $cnf

  catch {remove_design -all}
}

if {$RUN_FINAL_TABLES} {
  puts "INFO: building final requested SI feature tables"
  set ::env(SI_FEATURE_ANALYSIS) $ANALYSIS
  set ::env(SI_FEATURE_ACTIVE_DIR) "$ACTIVE_OUT/active_only_by_corner"
  set ::env(SI_FEATURE_ACTIVE_INDEX) "$ACTIVE_OUT/active_only_by_corner/index.tsv"
  set ::env(SI_FEATURE_WINDOW_FILE) "$WINDOW_OUT/all_voltages_net_driver_timing_windows.tsv"
  set ::env(SI_FEATURE_VICTIM_LOAD_WINDOW_FILE) "$WINDOW_OUT/all_voltages_victim_path_load_windows.tsv"
  set ::env(SI_FEATURE_OUT_DIR) $REQUESTED_OUT
  set ::env(SI_FEATURE_RAW_ATTR_FILE) "$REQUESTED_OUT/requested_si_attrs.raw_net_attrs.tsv"
  set ::env(SI_FEATURE_SPEF) $SPEF
  puts [exec $PYTHON_BIN $FINAL_TABLE_SCRIPT]
}

puts "DONE: unified SI feature extraction flow complete"
exit
