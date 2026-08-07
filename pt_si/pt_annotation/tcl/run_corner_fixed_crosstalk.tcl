# run_corner_fixed_crosstalk.tcl
#
# 목적: **PT 세션 하나**에서 fixed-path 타이밍 리포트와 crosstalk feature 를 함께 뽑는다.
#
# 기존 흐름은 코너 하나당 pt_shell 이 3번 뜬다:
#   ① pt_annotation/tcl/run_corner_fixed.tcl                    -> fixed report
#   ② crosstalk_features/.../dump_path_context_delay_calculation.tcl -> crosstalk delta
#   ③ crosstalk_features/.../dump_compact_timing_windows.tcl         -> timing window
# 셋 다 read_verilog / link_design / read_parasitics / update_timing 를 반복하는데,
# 큰 SPEF 에서는 이 셋업이 실행 시간의 대부분이다. 이 파일은 셋업을 1회로 줄인다.
#
# 합칠 수 있는 근거: crosstalk ①단계 파서(parse_annotated_with_clock_segments.py)는
# Dist/Res/Cpin 을 쓰지 않고 FIXED_PATH 헤더·핀 라인·slack 만 읽는다. 즉 annotation
# **이전**의 report_fixed_paths 출력만으로 victim 목록을 만들 수 있다. (같은 코너의
# raw rpt 와 annotated 파일을 각각 넣어 victim_net/driver/load 컬럼이 완전히 동일함을
# 확인했다. dist/res/cpin 컬럼만 raw 쪽이 비며, 그 컬럼들은 최종 14컬럼 리포트에
# 포함되지 않는다.)
#
# Dist/Res/Cpin annotation 은 PT 가 아니라 파이썬(res.py)이 하므로 이 세션 밖에서
# 언제든 붙이면 된다. 이 파일은 PT 가 해야 할 일만 담는다.
#
# 산출물:
#   $OUT_RPT                                  fixed-path 타이밍 리포트 (res.py 입력)
#   $XT_OUT_DIR/path_summary.tsv              경로 요약
#   $XT_OUT_DIR/path_victim_nets.tsv          경로별 victim arc
#   $XT_OUT_DIR/unique_path_arc_contexts.tsv  중복 제거된 조회 대상
#   $XT_OUT_DIR/path_context_report_delay_calculation.raw.rpt  crosstalk 원문
#   $XT_OUT_DIR/compact_{victim_load_pin,aggressor_driver}_windows.tsv  timing window
#   $XT_OUT_DIR/compact_path_context_features.by_path.rpt      최종 14컬럼
#
# 환경변수:
#   [타이밍]  TOP VERILOG SDC SPEF LIB_DB FIXED_TCL OUT_RPT
#             DELAY_TYPE(max|min) EXTRA_LIBS FORCE_BASIC_RC PBA_MODE SI
#   [crosstalk] XT_ENABLE(1이면 수행) XT_OUT_DIR XT_PARSERS
#             XT_PYTHON(기본 python3) XT_MAX_CONTEXTS(0=전체)
#             XT_FEATURE_CORNER XT_FEATURE_ANALYSIS_TYPE
#             XT_FEATURE_VOLTAGE XT_FEATURE_TEMPERATURE
#
# crosstalk 단계는 **SI=1 필수**다(coupling 없는 parasitics 로는 aggressor 가 안 잡힌다).

proc xt_getenv {name {default ""}} {
  if {[info exists ::env($name)] && $::env($name) ne ""} {
    return $::env($name)
  }
  return $default
}

proc xt_sanitize {s} {
  return [string map {"\t" " " "\n" " " "\r" " "} $s]
}

# 파이썬 단계 실행. 실패하면 즉시 중단한다 -- 중간 산출물이 비면 뒤 단계가
# 조용히 빈 결과를 내므로, 여기서 끊는 편이 진단이 쉽다.
proc xt_run_python {label script args} {
  set py [xt_getenv XT_PYTHON "python3"]
  set cmd [linsert $args 0 exec $py $script]
  puts "INFO: \[$label\] $py $script $args"
  if {[catch {eval $cmd} out]} {
    puts stderr "ERROR: \[$label\] failed: $out"
    exit 3
  }
  if {[string trim $out] ne ""} {
    puts $out
  }
}

# ---------------------------------------------------------------- 입력
set TOP       [xt_getenv TOP]
set VERILOG   [xt_getenv VERILOG]
set SDC       [xt_getenv SDC]
set SPEF      [xt_getenv SPEF]
set LIB_DB    [xt_getenv LIB_DB]
set FIXED_TCL [xt_getenv FIXED_TCL]
set OUT_RPT   [xt_getenv OUT_RPT]

set EXTRA_LIBS     [xt_getenv EXTRA_LIBS]
set SI             [xt_getenv SI]
set FORCE_BASIC_RC [xt_getenv FORCE_BASIC_RC]
set DELAY_TYPE     [xt_getenv DELAY_TYPE max]

set XT_ENABLE   [xt_getenv XT_ENABLE 0]
set XT_OUT_DIR  [xt_getenv XT_OUT_DIR]
set XT_PARSERS  [xt_getenv XT_PARSERS]
set XT_MAX_CTX  [xt_getenv XT_MAX_CONTEXTS 0]

foreach v {TOP VERILOG SDC SPEF LIB_DB FIXED_TCL OUT_RPT} {
  if {[xt_getenv $v] eq ""} {
    puts stderr "ERROR: env var $v is empty"
    exit 2
  }
}

if {$XT_ENABLE eq "1"} {
  foreach v {XT_OUT_DIR XT_PARSERS} {
    if {[xt_getenv $v] eq ""} {
      puts stderr "ERROR: XT_ENABLE=1 requires env var $v"
      exit 2
    }
  }
  if {$SI ne "1"} {
    # grounded parasitics 로 crosstalk 를 돌리면 aggressor 가 0건이라 결과가 전부 0 이
    # 된다. 조용히 쓸모없는 데이터를 만드느니 여기서 막는다.
    puts stderr "ERROR: XT_ENABLE=1 requires SI=1 (crosstalk needs coupled parasitics)"
    exit 2
  }
  file mkdir $XT_OUT_DIR
}

# ---------------------------------------------------------------- 셋업 (1회)
if {$SI eq "1"} {
  set_app_var si_enable_analysis true
  puts "INFO: si_enable_analysis = [get_app_var si_enable_analysis]"
}
if {$XT_ENABLE eq "1"} {
  # crosstalk 2단계에서 get_attribute 로 핀별 arrival 을 읽으려면 필요하다.
  # 이걸 안 켜면 window 값이 전부 빈 값으로 나온다.
  set_app_var timing_save_pin_arrival_and_slack true
}
if {$FORCE_BASIC_RC eq "1"} {
  set_app_var rc_driver_model_mode basic
  set_app_var rc_receiver_model_mode basic
  puts "INFO: FORCE_BASIC_RC enabled"
}

file mkdir [file dirname $OUT_RPT]

read_verilog $VERILOG
current_design $TOP

if {$EXTRA_LIBS ne ""} {
  set link_path "* $LIB_DB $EXTRA_LIBS"
} else {
  set link_path "* $LIB_DB"
}
link_design

read_sdc $SDC
if {$SI eq "1"} {
  read_parasitics -keep_capacitive_coupling $SPEF
} else {
  read_parasitics $SPEF
}
set_propagated_clock [all_clocks]
update_timing

# ---------------------------------------------------------------- PHASE 1: fixed-path 리포트
source $FIXED_TCL
set _this_dir [file dirname [info script]]
source [file join $_this_dir report_fixed_paths.tcl]

report_fixed_paths $OUT_RPT
puts "DONE: phase1 wrote $OUT_RPT"

if {$XT_ENABLE ne "1"} {
  puts "INFO: XT_ENABLE != 1 -- crosstalk phases skipped"
  exit
}

# ---------------------------------------------------------------- PHASE 2: victim 목록 (python)
# 파일명은 crosstalk_features/path_context_sweep/run_sweep.py 의 work 파일명과 동일하게
# 맞춘다. 그래야 같은 파서들이 그대로 소비하고, 결과를 기존 흐름과 비교할 수 있다.
set PATH_SUMMARY   [file join $XT_OUT_DIR "path_summary.tsv"]
set PATH_VICTIM    [file join $XT_OUT_DIR "path_victim_nets.tsv"]
set UNIQUE_CTX     [file join $XT_OUT_DIR "unique_path_arc_contexts.tsv"]
set CTX_RAW        [file join $XT_OUT_DIR "path_context_report_delay_calculation.raw.rpt"]
set CTX_MANIFEST   [file join $XT_OUT_DIR "path_context_report_delay_calculation_manifest.tsv"]
set CTX_SUMMARY    [file join $XT_OUT_DIR "path_context_delay_calculation_summary.tsv"]
set ACTIVE_FEAT    [file join $XT_OUT_DIR "path_context_active_aggressor_features.tsv"]
set VICTIM_PINS    [file join $XT_OUT_DIR "compact_victim_load_pins.txt"]
set AGGRESSOR_NETS [file join $XT_OUT_DIR "compact_aggressor_nets.txt"]
set VICTIM_WIN     [file join $XT_OUT_DIR "compact_victim_load_pin_windows.tsv"]
set AGGRESSOR_WIN  [file join $XT_OUT_DIR "compact_aggressor_driver_windows.tsv"]
set FLAT_OUT       [file join $XT_OUT_DIR "compact_path_context_features.flat.tsv"]
set BY_PATH_OUT    [file join $XT_OUT_DIR "compact_path_context_features.by_path.rpt"]

# 여기 입력이 annotated 파일이 아니라 방금 만든 $OUT_RPT 라는 점이 이 통합의 핵심이다.
xt_run_python "01_parse_paths" \
  [file join $XT_PARSERS "parse_annotated_with_clock_segments.py"] \
  $OUT_RPT $PATH_SUMMARY $PATH_VICTIM

xt_run_python "02_unique_contexts" \
  [file join $XT_PARSERS "make_unique_path_arc_contexts.py"] \
  $PATH_VICTIM $UNIQUE_CTX

# ---------------------------------------------------------------- PHASE 3: crosstalk delta (PT)
# dump_path_context_delay_calculation.tcl 의 루프와 동일한 동작.
proc xt_write_raw_block {fh context_id victim driver load status message report_text} {
  puts $fh "### PATH_CONTEXT_BEGIN"
  puts $fh "### context_id=[xt_sanitize $context_id]"
  puts $fh "### victim_net=[xt_sanitize $victim]"
  puts $fh "### victim_driver_pin=[xt_sanitize $driver]"
  puts $fh "### victim_load_pin=[xt_sanitize $load]"
  puts $fh "### status=[xt_sanitize $status]"
  puts $fh "### message=[xt_sanitize $message]"
  if {$report_text ne ""} {
    puts $fh $report_text
  }
  puts $fh "### PATH_CONTEXT_END"
}

set cf [open $UNIQUE_CTX r]
gets $cf header
set rf [open $CTX_RAW w]
set mf [open $CTX_MANIFEST w]
puts $mf "context_id\tvictim_net\tvictim_driver_pin\tvictim_load_pin\treport_status\tmessage"

set total 0
set ok_count 0
set err_count 0
while {[gets $cf line] >= 0} {
  if {[string trim $line] eq ""} {
    continue
  }
  incr total
  if {$XT_MAX_CTX > 0 && $total > $XT_MAX_CTX} {
    incr total -1
    break
  }

  set fields [split $line "\t"]
  set context_id [lindex $fields 0]
  set victim     [lindex $fields 1]
  set driver     [lindex $fields 2]
  set load       [lindex $fields 3]
  set status "OK"
  set message ""
  set report_text ""

  set from_obj [get_pins -quiet $driver]
  set to_obj   [get_pins -quiet $load]
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
  puts $mf "$context_id\t[xt_sanitize $victim]\t[xt_sanitize $driver]\t[xt_sanitize $load]\t$status\t[xt_sanitize $message]"
  xt_write_raw_block $rf $context_id $victim $driver $load $status $message $report_text

  if {[expr {$total % 100}] == 0} {
    puts "INFO: phase3 processed $total contexts ok=$ok_count err=$err_count"
    flush $rf
    flush $mf
  }
}
close $cf
close $rf
close $mf
puts "DONE: phase3 contexts=$total ok=$ok_count err=$err_count"

# ---------------------------------------------------------------- PHASE 4: delta 파싱 + window 요청 (python)
# 파서가 feature 컬럼 라벨에 쓰는 값. 러너가 안 주면 빈 문자열로 두되, 그 경우
# 최종 리포트의 corner 라벨이 비므로 러너 쪽에서 채우는 것을 권장한다.
set ::env(PT_FEATURE_CORNER)        [xt_getenv XT_FEATURE_CORNER]
set ::env(PT_FEATURE_ANALYSIS_TYPE) [xt_getenv XT_FEATURE_ANALYSIS_TYPE]
set ::env(PT_FEATURE_VOLTAGE)       [xt_getenv XT_FEATURE_VOLTAGE]
set ::env(PT_FEATURE_TEMPERATURE)   [xt_getenv XT_FEATURE_TEMPERATURE]

xt_run_python "04_parse_context" \
  [file join $XT_PARSERS "parse_path_context_delay_calculation.py"] \
  $PATH_VICTIM $UNIQUE_CTX $CTX_RAW $CTX_SUMMARY $ACTIVE_FEAT

xt_run_python "05_prepare_windows" \
  [file join $XT_PARSERS "prepare_compact_timing_window_requests.py"] \
  $ACTIVE_FEAT $VICTIM_PINS $AGGRESSOR_NETS

# ---------------------------------------------------------------- PHASE 5: timing window (PT)
# dump_compact_timing_windows.tcl 과 동일한 동작.
proc xt_attr_or_empty {obj attr} {
  if {$obj eq ""} {
    return ""
  }
  set rc [catch {get_attribute $obj $attr} val]
  if {$rc != 0} {
    return ""
  }
  return [xt_sanitize $val]
}

proc xt_numeric_min {values} {
  set seen 0
  set best 0.0
  foreach val $values {
    if {$val eq ""} { continue }
    if {!$seen || $val < $best} { set best $val; set seen 1 }
  }
  if {!$seen} { return "" }
  return $best
}

proc xt_numeric_max {values} {
  set seen 0
  set best 0.0
  foreach val $values {
    if {$val eq ""} { continue }
    if {!$seen || $val > $best} { set best $val; set seen 1 }
  }
  if {!$seen} { return "" }
  return $best
}

proc xt_pin_window_row {pin_name} {
  set pin [get_pins -quiet $pin_name]
  if {[sizeof_collection $pin] == 0} {
    return [list [xt_sanitize $pin_name] "" "" "" "" "" "" "" "PIN_NOT_FOUND"]
  }
  set min_rise  [xt_attr_or_empty $pin min_rise_arrival]
  set max_rise  [xt_attr_or_empty $pin max_rise_arrival]
  set min_fall  [xt_attr_or_empty $pin min_fall_arrival]
  set max_fall  [xt_attr_or_empty $pin max_fall_arrival]
  set rise_slew [xt_attr_or_empty $pin actual_rise_transition_max]
  set fall_slew [xt_attr_or_empty $pin actual_fall_transition_max]
  set overall_min [xt_numeric_min [list $min_rise $min_fall]]
  set overall_max [xt_numeric_max [list $max_rise $max_fall]]
  set slew_max    [xt_numeric_max [list $rise_slew $fall_slew]]
  return [list [xt_sanitize $pin_name] $overall_min $overall_max $min_rise $max_rise $min_fall $max_fall $slew_max "OK"]
}

# hierarchy boundary 의 포트 핀이 잡히면 slew 가 0 으로 나온다. -leaf 로 회피한다.
proc xt_first_driver_pin {net_name} {
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

set vf [open $VICTIM_PINS r]
set vo [open $VICTIM_WIN w]
puts $vo "victim_load_pin\tvictim_load_min_arrival\tvictim_load_max_arrival\tmin_rise\tmax_rise\tmin_fall\tmax_fall\tslew_max\tstatus"
set vcount 0
while {[gets $vf line] >= 0} {
  set pin_name [string trim $line]
  if {$pin_name eq ""} { continue }
  incr vcount
  puts $vo [join [xt_pin_window_row $pin_name] "\t"]
}
close $vf
close $vo

set nf [open $AGGRESSOR_NETS r]
set ao [open $AGGRESSOR_WIN w]
puts $ao "aggressor_net\taggressor_driver_pin\taggressor_driver_min_arrival\taggressor_driver_max_arrival\tmin_rise\tmax_rise\tmin_fall\tmax_fall\taggressor_driver_slew_max\tstatus"
set acount 0
while {[gets $nf line] >= 0} {
  set net_name [string trim $line]
  if {$net_name eq ""} { continue }
  incr acount
  set driver_pin [xt_first_driver_pin $net_name]
  if {$driver_pin eq ""} {
    puts $ao "[xt_sanitize $net_name]\t\t\t\t\t\t\t\t\tNO_DRIVER"
    continue
  }
  set w [xt_pin_window_row $driver_pin]
  puts $ao "[xt_sanitize $net_name]\t[join $w "\t"]"
}
close $nf
close $ao
puts "DONE: phase5 victim_pins=$vcount aggressor_nets=$acount"

# ---------------------------------------------------------------- PHASE 6: 최종 리포트 (python)
xt_run_python "07_make_rpt" \
  [file join $XT_PARSERS "make_compact_path_context_report.py"] \
  $ACTIVE_FEAT $PATH_VICTIM $VICTIM_WIN $AGGRESSOR_WIN $FLAT_OUT $BY_PATH_OUT

puts "DONE: unified corner run"
puts "  timing report : $OUT_RPT"
puts "  crosstalk rpt : $BY_PATH_OUT"
exit
