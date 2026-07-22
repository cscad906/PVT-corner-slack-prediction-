set TOP "BoomCore"

proc require_env {name} {
  if {![info exists ::env($name)] || $::env($name) eq ""} {
    puts stderr "ERROR: missing environment variable $name"
    exit 1
  }
  return $::env($name)
}

proc sanitize {s} {
  return [string map {"\t" " " "\n" " " "\r" " "} $s]
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

proc pin_window_row {pin_name} {
  set pin [get_pins -quiet $pin_name]
  if {[sizeof_collection $pin] == 0} {
    return [list [sanitize $pin_name] "" "" "" "" "" "" "" "PIN_NOT_FOUND"]
  }
  set min_rise [attr_or_empty $pin min_rise_arrival]
  set max_rise [attr_or_empty $pin max_rise_arrival]
  set min_fall [attr_or_empty $pin min_fall_arrival]
  set max_fall [attr_or_empty $pin max_fall_arrival]
  set rise_slew [attr_or_empty $pin actual_rise_transition_max]
  set fall_slew [attr_or_empty $pin actual_fall_transition_max]
  set overall_min [numeric_min [list $min_rise $min_fall]]
  set overall_max [numeric_max [list $max_rise $max_fall]]
  set slew_max [numeric_max [list $rise_slew $fall_slew]]
  return [list [sanitize $pin_name] $overall_min $overall_max $min_rise $max_rise $min_fall $max_fall $slew_max "OK"]
}

proc first_driver_pin {net_name} {
  set net [get_nets -quiet $net_name]
  if {[sizeof_collection $net] == 0} {
    return ""
  }
  set leaf_pins ""
  set leaf_rc [catch {
    set leaf_pins [get_pins -quiet -leaf -of_objects $net -filter "direction == out || direction == inout"]
  }]
  if {$leaf_rc == 0 && [sizeof_collection $leaf_pins] > 0} {
    return [get_object_name [index_collection $leaf_pins 0]]
  }
  set pins [get_pins -quiet -of_objects $net -filter "direction == out || direction == inout"]
  if {[sizeof_collection $pins] == 0} {
    return ""
  }
  return [get_object_name [index_collection $pins 0]]
}

set VERILOG [require_env PT_VERILOG]
set SDC [require_env PT_SDC]
set DB [require_env PT_DB]
set SPEF [require_env PT_SPEF]
set OUT_DIR [require_env PT_COMPACT_OUT_DIR]
set VICTIM_PIN_LIST "$OUT_DIR/compact_victim_load_pins.txt"
set AGGRESSOR_NET_LIST "$OUT_DIR/compact_aggressor_nets.txt"
set VICTIM_OUT "$OUT_DIR/compact_victim_load_pin_windows.tsv"
set AGGRESSOR_OUT "$OUT_DIR/compact_aggressor_driver_windows.tsv"

foreach f [list $VERILOG $SDC $SPEF $DB $VICTIM_PIN_LIST $AGGRESSOR_NET_LIST] {
  if {![file exists $f]} {
    puts stderr "ERROR: missing file: $f"
    exit 1
  }
}

set_app_var si_enable_analysis true
set_app_var timing_save_pin_arrival_and_slack true
read_verilog $VERILOG
current_design $TOP
set link_path "* $DB"
link_design
read_sdc $SDC
read_parasitics -format spef -keep_capacitive_coupling $SPEF
set_propagated_clock [all_clocks]
update_timing

set vf [open $VICTIM_PIN_LIST r]
set vo [open $VICTIM_OUT w]
puts $vo "victim_load_pin\tvictim_load_min_arrival\tvictim_load_max_arrival\tmin_rise\tmax_rise\tmin_fall\tmax_fall\tslew_max\tstatus"
set vcount 0
while {[gets $vf line] >= 0} {
  set pin_name [string trim $line]
  if {$pin_name eq ""} {
    continue
  }
  incr vcount
  puts $vo [join [pin_window_row $pin_name] "\t"]
}
close $vf
close $vo

set nf [open $AGGRESSOR_NET_LIST r]
set ao [open $AGGRESSOR_OUT w]
puts $ao "aggressor_net\taggressor_driver_pin\taggressor_driver_min_arrival\taggressor_driver_max_arrival\tmin_rise\tmax_rise\tmin_fall\tmax_fall\taggressor_driver_slew_max\tstatus"
set acount 0
while {[gets $nf line] >= 0} {
  set net_name [string trim $line]
  if {$net_name eq ""} {
    continue
  }
  incr acount
  set driver_pin [first_driver_pin $net_name]
  if {$driver_pin eq ""} {
    puts $ao "[sanitize $net_name]\t\t\t\t\t\t\t\t\tNO_DRIVER"
    continue
  }
  set w [pin_window_row $driver_pin]
  puts $ao "[sanitize $net_name]\t[join $w "\t"]"
}
close $nf
close $ao

puts "DONE: victim_pins=$vcount aggressor_nets=$acount victim_out=$VICTIM_OUT aggressor_out=$AGGRESSOR_OUT"
exit
