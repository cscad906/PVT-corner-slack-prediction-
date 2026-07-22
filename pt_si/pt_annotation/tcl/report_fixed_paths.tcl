# report_fixed_paths.tcl
# 사용:
# source fixed_paths.tcl
# source report_fixed_paths.tcl
# report_fixed_paths "result/TT_0p8v25c_fixed.rpt"

proc fixed_path_edge_opt {base_opt dir} {
  if {$dir eq "r"} {
    return "-rise_$base_opt"
  }
  if {$dir eq "f"} {
    return "-fall_$base_opt"
  }
  return "-$base_opt"
}

proc report_fixed_paths {out_file} {
  global FIXED_PATHS
  set delay_type [getenv DELAY_TYPE]
  if {$delay_type eq ""} {
    set delay_type max
  }
  set pba_mode [getenv PBA_MODE]
  if {[info exists ::env(SIGNIFICANT_DIGITS)] && $::env(SIGNIFICANT_DIGITS) ne ""} {
    set significant_digits $::env(SIGNIFICANT_DIGITS)
  } else {
    set significant_digits 4
  }

  # 기존 파일 지우고 새로
  file delete -force $out_file

  set idx 0
  foreach item $FIXED_PATHS {
    incr idx
    # item 구조:
    #   legacy:     {path_key {from_pin} {to_pin} { {thr1} {thr2} ... }}
    #   edge-aware: {path_key {from_pin} {to_pin} { {thr1} {thr2} ... } {from_dir through_dir... to_dir}}
    set path_key  [lindex $item 0]
    set from_pin  [lindex $item 1]
    set to_pin    [lindex $item 2]
    set thr_list  [lindex $item 3]
    set edge_list {}
    if {[llength $item] >= 5} {
      set edge_list [lindex $item 4]
    }
    set use_edges 0
    if {[llength $edge_list] == [expr {[llength $thr_list] + 2}]} {
      set use_edges 1
    }

    # 핀 이름에 [ ] 가 있어서 반드시 { }로 감싸 get_pins 해야 함
    set from_obj [get_pins -quiet $from_pin]
    set to_obj   [get_pins -quiet $to_pin]

    if {[sizeof_collection $from_obj] == 0 || [sizeof_collection $to_obj] == 0} {
      puts "[format {WARN idx=%d %s : from/to pin not found} $idx $path_key]"
      continue
    }

    set from_opt "-from"
    set to_opt "-to"
    if {$use_edges} {
      set from_opt [fixed_path_edge_opt "from" [lindex $edge_list 0]]
      set to_opt [fixed_path_edge_opt "to" [lindex $edge_list end]]
    }

    # report_timing 커맨드 생성
    set cmd "report_timing -delay_type $delay_type -path_type full_clock_expanded \
      $from_opt \[get_pins -quiet {$from_pin}\] \
      $to_opt   \[get_pins -quiet {$to_pin}\] \
      -max_paths 1 -sort_by slack \
      -input_pins -nets -capacitance -transition_time \
      -nosplit -significant_digits $significant_digits"

    if {$pba_mode ne ""} {
      append cmd " -pba_mode {$pba_mode}"
    }

    # through 추가(있으면)
    set through_idx 0
    foreach tp $thr_list {
      set through_opt "-through"
      if {$use_edges} {
        set through_opt [fixed_path_edge_opt "through" [lindex $edge_list [expr {$through_idx + 1}]]]
      }
      append cmd " $through_opt \[get_pins -quiet {$tp}\]"
      incr through_idx
    }

    # 파일에 append
    redirect -append $out_file {
      puts "### FIXED_PATH idx=$idx key=$path_key"
      eval $cmd
      puts ""
    }
  }

  puts "[format {DONE wrote fixed reports to %s} $out_file]"
}
