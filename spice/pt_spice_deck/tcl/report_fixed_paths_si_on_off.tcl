# Report the same fixed paths with PrimeTime SI disabled and enabled.
#
# Required environment variables:
#   TOP, VERILOG, SDC, SPEF, LIB_DB, FIXED_TCL, OUT_DIR, FIXED_INDEXES

proc env_required {name} {
  if {![info exists ::env($name)] || [string trim $::env($name)] eq ""} {
    puts stderr "ERROR: required environment variable $name is empty"
    exit 2
  }
  return $::env($name)
}

proc safe_set_app_var {name value} {
  if {[catch {set_app_var $name $value} msg]} {
    puts "WARN: could not set_app_var $name=$value: $msg"
  }
}

proc build_report_cmd {item delay_type} {
  set from_obj [get_pins -quiet [lindex $item 1]]
  set to_obj [get_pins -quiet [lindex $item 2]]
  if {[sizeof_collection $from_obj] == 0 || [sizeof_collection $to_obj] == 0} {
    return {}
  }

  set cmd [list report_timing \
    -path_type full_clock_expanded \
    -delay_type $delay_type \
    -from $from_obj \
    -to $to_obj \
    -max_paths 1 \
    -sort_by slack \
    -input_pins \
    -nets \
    -capacitance \
    -transition_time \
    -nosplit \
    -significant_digits 6]

  foreach through_pin [lindex $item 3] {
    set through_obj [get_pins -quiet $through_pin]
    if {[sizeof_collection $through_obj] > 0} {
      lappend cmd -through $through_obj
    }
  }
  return $cmd
}

set TOP           [env_required TOP]
set VERILOG       [env_required VERILOG]
set SDC           [env_required SDC]
set SPEF          [env_required SPEF]
set LIB_DB        [env_required LIB_DB]
set FIXED_TCL     [env_required FIXED_TCL]
set OUT_DIR       [env_required OUT_DIR]
set FIXED_INDEXES [env_required FIXED_INDEXES]
set DELAY_TYPE    [expr {[info exists ::env(DELAY_TYPE)] ? $::env(DELAY_TYPE) : "max"}]

file mkdir $OUT_DIR
set search_path [list . [file dirname $VERILOG] [file dirname $LIB_DB]]
set target_library [list $LIB_DB]
set link_path "* $LIB_DB"

safe_set_app_var timing_disable_cond_default_arcs true
safe_set_app_var timing_report_use_worst_parallel_cell_arc false
safe_set_app_var delay_calc_waveform_analysis_mode full_design
safe_set_app_var timing_keep_waveform_on_points true

read_verilog $VERILOG
current_design $TOP
link_design
read_sdc $SDC
read_parasitics -keep_capacitive_coupling $SPEF
set_propagated_clock [all_clocks]
source $FIXED_TCL

set audit_path [file join $OUT_DIR "si_mode_audit.rpt"]
set audit [open $audit_path w]
puts $audit "PrimeTime SI mode audit"

foreach mode {off on} {
  set si_enabled [expr {$mode eq "on"}]
  safe_set_app_var si_enable_analysis $si_enabled
  update_timing -full
  set applied_mode [get_app_var si_enable_analysis]
  puts $audit "mode=$mode requested=$si_enabled applied=$applied_mode"
  flush $audit

  foreach fixed_index $FIXED_INDEXES {
    if {$fixed_index < 1 || $fixed_index > [llength $FIXED_PATHS]} {
      puts "WARN: fixed index out of range: $fixed_index"
      continue
    }
    set item [lindex $FIXED_PATHS [expr {$fixed_index - 1}]]
    set cmd [build_report_cmd $item $DELAY_TYPE]
    if {[llength $cmd] == 0} {
      puts "WARN: path endpoint not found for fixed index $fixed_index"
      continue
    }
    set output [file join $OUT_DIR "path${fixed_index}_si_${mode}.rpt"]
    redirect $output {
      puts "### FIXED_PATH idx=$fixed_index key=[lindex $item 0] SI=$mode"
      eval $cmd
    }
    puts "INFO: wrote $output"

    set delta_output [file join $OUT_DIR "path${fixed_index}_si_${mode}_crosstalk_delta.rpt"]
    set delta_cmd [concat $cmd -crosstalk_delta]
    if {[catch {
      redirect $delta_output {
        puts "### FIXED_PATH idx=$fixed_index key=[lindex $item 0] SI=$mode CROSSTALK_DELTA"
        eval $delta_cmd
      }
    } delta_message]} {
      set delta_file [open $delta_output w]
      puts $delta_file "REPORT_FAILED: $delta_message"
      close $delta_file
    }
    puts "INFO: wrote $delta_output"
  }
}

close $audit
exit
