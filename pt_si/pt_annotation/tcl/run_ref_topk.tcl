# run_ref_topk.tcl
# 목적: ref 코너(.db)에서 topK 경로를 report 파일로 저장한다.
# 입력은 환경변수로 받는다.
# SI=1 이면 PrimeTime SI 분석(coupling 유지), 아니면 일반 분석.

set TOP     [getenv TOP]
set VERILOG [getenv VERILOG]
set SDC     [getenv SDC]
set SPEF    [getenv SPEF]
set LIB_DB  [getenv LIB_DB]     ;# ref db
set OUT_RPT [getenv OUT_RPT]    ;# ref_topK.rpt

set MAX_PATHS [getenv MAX_PATHS]
if {$MAX_PATHS eq ""} { set MAX_PATHS 1000 }

set NWORST [getenv NWORST]
if {$NWORST eq ""} { set NWORST 1 }

set SLACK_TH  [getenv SLACK_TH]
if {$SLACK_TH eq ""} { set SLACK_TH 1.0 }

set DELAY_TYPE [getenv DELAY_TYPE]
if {$DELAY_TYPE eq ""} { set DELAY_TYPE max }

set FORCE_BASIC_RC [getenv FORCE_BASIC_RC]
if {$FORCE_BASIC_RC eq "1"} {
  set_app_var rc_driver_model_mode basic
  set_app_var rc_receiver_model_mode basic
  puts "INFO: FORCE_BASIC_RC enabled"
}

# (선택) 매크로/IO 등 추가 라이브러리
set EXTRA_LIBS [getenv EXTRA_LIBS]

set SI [getenv SI]
if {$SI eq "1"} {
  set_app_var si_enable_analysis true
  puts "INFO: si_enable_analysis = [get_app_var si_enable_analysis]"
  puts "INFO: read_parasitics uses -keep_capacitive_coupling"
}

foreach v {TOP VERILOG SDC SPEF LIB_DB OUT_RPT} {
  if {[getenv $v] eq ""} {
    puts "ERROR: env var $v is empty"
    exit 2
  }
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

# ref에서 topK 후보 경로를 뽑음 (이 파일을 python이 파싱해서 fixed_paths를 만든다)
redirect -file $OUT_RPT {
  report_timing \
    -delay_type $DELAY_TYPE -path_type full_clock_expanded \
    -nets -capacitance -transition_time -input_pins \
    -significant_digits 4 -nosplit \
    -nworst $NWORST \
    -max_paths $MAX_PATHS \
    -slack_lesser_than $SLACK_TH
}

puts "DONE: wrote $OUT_RPT"
exit
