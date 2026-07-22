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

proc write_raw_block {fh context_id victim driver load status message report_text} {
  puts $fh "### PATH_CONTEXT_BEGIN"
  puts $fh "### context_id=[sanitize $context_id]"
  puts $fh "### victim_net=[sanitize $victim]"
  puts $fh "### victim_driver_pin=[sanitize $driver]"
  puts $fh "### victim_load_pin=[sanitize $load]"
  puts $fh "### status=[sanitize $status]"
  puts $fh "### message=[sanitize $message]"
  if {$report_text ne ""} {
    puts $fh $report_text
  }
  puts $fh "### PATH_CONTEXT_END"
}

set VERILOG [require_env PT_VERILOG]
set SDC [require_env PT_SDC]
set DB [require_env PT_DB]
set SPEF [require_env PT_SPEF]
set OUT_DIR [require_env PT_CONTEXT_OUT_DIR]
set CONTEXT_TSV "$OUT_DIR/unique_path_arc_contexts.tsv"
set RAW_REPORT "$OUT_DIR/path_context_report_delay_calculation.raw.rpt"
set MANIFEST "$OUT_DIR/path_context_report_delay_calculation_manifest.tsv"
set DELAY_TYPE "max"
if {[info exists ::env(PT_DELAY_TYPE)] && $::env(PT_DELAY_TYPE) ne ""} {
  set DELAY_TYPE $::env(PT_DELAY_TYPE)
}
if {$DELAY_TYPE ne "max" && $DELAY_TYPE ne "min"} {
  puts stderr "ERROR: PT_DELAY_TYPE must be max or min, got $DELAY_TYPE"
  exit 1
}

set MAX_CONTEXTS 0
if {[info exists ::env(PT_CONTEXT_MAX_CONTEXTS)] && $::env(PT_CONTEXT_MAX_CONTEXTS) ne ""} {
  set MAX_CONTEXTS $::env(PT_CONTEXT_MAX_CONTEXTS)
}

foreach f [list $VERILOG $SDC $SPEF $DB $CONTEXT_TSV] {
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

set cf [open $CONTEXT_TSV r]
gets $cf header
set rf [open $RAW_REPORT w]
set mf [open $MANIFEST w]
puts $mf "context_id\tvictim_net\tvictim_driver_pin\tvictim_load_pin\treport_status\tmessage"

set total 0
set ok_count 0
set err_count 0
while {[gets $cf line] >= 0} {
  if {[string trim $line] eq ""} {
    continue
  }
  incr total
  if {$MAX_CONTEXTS > 0 && $total > $MAX_CONTEXTS} {
    incr total -1
    break
  }

  set fields [split $line "\t"]
  set context_id [lindex $fields 0]
  set victim [lindex $fields 1]
  set driver [lindex $fields 2]
  set load [lindex $fields 3]
  set status "OK"
  set message ""
  set report_text ""

  set from_obj [get_pins -quiet $driver]
  set to_obj [get_pins -quiet $load]
  if {[sizeof_collection $from_obj] == 0} {
    set status "ERROR"
    set message "DRIVER_PIN_NOT_FOUND"
  } elseif {[sizeof_collection $to_obj] == 0} {
    set status "ERROR"
    set message "LOAD_PIN_NOT_FOUND"
  } else {
    set rc [catch {
      if {$DELAY_TYPE eq "min"} {
        redirect -variable report_text {
          report_delay_calculation -crosstalk -min -from $from_obj -to $to_obj
        }
      } else {
        redirect -variable report_text {
          report_delay_calculation -crosstalk -max -from $from_obj -to $to_obj
        }
      }
    } err]
    if {$rc != 0} {
      set status "ERROR"
      set message $err
    }
  }

  if {$status eq "OK"} {
    incr ok_count
  } else {
    incr err_count
  }
  puts $mf "$context_id\t[sanitize $victim]\t[sanitize $driver]\t[sanitize $load]\t$status\t[sanitize $message]"
  write_raw_block $rf $context_id $victim $driver $load $status $message $report_text

  if {[expr {$total % 100}] == 0} {
    puts "INFO: processed $total contexts ok=$ok_count err=$err_count"
    flush $rf
    flush $mf
  }
}

close $cf
close $rf
close $mf
puts "DONE: contexts=$total ok=$ok_count err=$err_count raw=$RAW_REPORT manifest=$MANIFEST"
exit
