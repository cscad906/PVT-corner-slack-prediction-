# run_corner_fixed.tcl
# 목적: 특정 코너(.db)에서 fixed_paths를 따라 동일 경로 report 생성
# SI=1 이면 PrimeTime SI 분석(coupling 유지), 아니면 일반 분석.

set TOP       [getenv TOP]
set VERILOG   [getenv VERILOG]
set SDC       [getenv SDC]
set SPEF      [getenv SPEF]
set LIB_DB    [getenv LIB_DB]        ;# target db
set FIXED_TCL [getenv FIXED_TCL]     ;# fixed_paths/designX_fixed_paths.tcl
set OUT_RPT   [getenv OUT_RPT]       ;# reports/designX/CORNER_fixed.rpt

set EXTRA_LIBS [getenv EXTRA_LIBS]

set SI [getenv SI]
if {$SI eq "1"} {
  set_app_var si_enable_analysis true
  puts "INFO: si_enable_analysis = [get_app_var si_enable_analysis]"
  puts "INFO: read_parasitics uses -keep_capacitive_coupling"
}

set FORCE_BASIC_RC [getenv FORCE_BASIC_RC]
if {$FORCE_BASIC_RC eq "1"} {
  set_app_var rc_driver_model_mode basic
  set_app_var rc_receiver_model_mode basic
  puts "INFO: FORCE_BASIC_RC enabled"
}

foreach v {TOP VERILOG SDC SPEF LIB_DB FIXED_TCL OUT_RPT} {
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

# 고정 경로 리스트 + 공용 리포트 함수 로드
source $FIXED_TCL
set _this_dir [file dirname [info script]]
source [file join $_this_dir report_fixed_paths.tcl]

# 동일 경로 report 생성
report_fixed_paths $OUT_RPT

puts "DONE: wrote $OUT_RPT"
exit
