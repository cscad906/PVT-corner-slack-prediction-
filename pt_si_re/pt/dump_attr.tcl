# =====================================================================
# dump_attr.tcl
#
#   pt_shell> source dump_attr.tcl
#
# report_timing 으로 만든 리포트에 등장하는 핀과 넷의 속성을 파일로 저장한다.
#   pin_attr.txt  <- Cpin, arrival window, slew
#   net_attr.txt  <- crosstalk delta, aggressor, coupling cap
#
# ---------------------------------------------------------------------
# 쓰는 순서
#   1) 먼저 리포트를 만든다 (직접 실행)
#        report_timing -delay_type max -path_type full_clock_expanded \
#          -nets -capacitance -transition_time -input_pins \
#          -nosplit -significant_digits 6 \
#          -nworst 3 -max_paths 3000 -slack_lesser_than 0.05 > timing.rpt
#   2) 아래 두 줄만 자기 경로로 바꾼다
#   3) source dump_attr.tcl
# ---------------------------------------------------------------------


### 여기 두 줄이 기본값 ###############################################
if {![info exists OUTDIR]} { set OUTDIR "." }                        ;# 결과를 저장할 폴더
if {![info exists RPT]}    { set RPT [lindex [glob -nocomplain -directory $OUTDIR *.rpt] 0] }
#######################################################################
# 기본값은 "지금 있는 폴더에 있는 .rpt". pt_shell 에서 그 코너 폴더로 cd 해
# 두었으면 아무것도 안 고쳐도 된다.
#     cd /data/round2/tt0p7v25c_Cnom   ->   source dump_attr.tcl
# 리포트가 여러 개거나 다른 곳에 있으면 미리 정해 준다.
#     set RPT "/data/round2/tt0p7v25c_Cnom/tt0p7v25c_Cnom.rpt"

if {$RPT eq "" || ![file exists $RPT]} {
    puts "=================================================================="
    puts "  문제 발생"
    puts "    무엇이   : 읽을 리포트(.rpt)를 못 찾았습니다."
    puts "               찾아본 곳: $OUTDIR"
    puts "    하실 일  : 2회차를 먼저 돌리세요 ->  source fixed_paths.tcl"
    puts "               리포트가 다른 곳에 있으면  set RPT \"<파일>\"  후 다시."
    puts ""
    puts "    에러 코드: E-NORPTFILE"
    puts "=================================================================="
    return
}


# 뽑을 속성 목록. 여기 있는 것만 저장한다.
# 지정하지 않으면 PT 가 속성 200개를 다 뱉어 파일이 20배 커진다
# (핀 9천개 기준 210MB -> 약 10MB). 필요한 것이 생기면 여기에 추가한다.
set PIN_ATTRS {
    pin_capacitance_max pin_capacitance_min
    min_rise_arrival max_rise_arrival min_fall_arrival max_fall_arrival
    actual_rise_transition_max actual_fall_transition_max
}
set NET_ATTRS {
    annotated_delay_delta_max annotated_delay_delta_min
    number_of_aggressors number_of_effective_aggressors
    total_coupling_capacitance total_effective_coupling_capacitance
    effective_aggressors si_xtalk_bumps
    net_resistance_max total_capacitance
}


# --- 리포트에 나온 이름을 모아 주는 함수 (내용은 안 봐도 된다) ---------
# 전체 핀을 덤프하면 파일이 9GB 를 넘어 쓸 수가 없다. 그래서 리포트에 실제로
# 등장하는 것만 골라 뽑는다. kind 에 "pin" 또는 "net" 을 준다.
proc names_in_report {rpt kind} {
    set out {}
    set fh [open $rpt r]
    while {[gets $fh line] >= 0} {
        if {![regexp {^\s\s+(\S+)\s+\(([^)]+)\)} $line -> nm tag]} continue
        set is_net [string equal -nocase $tag "net"]
        if {$kind eq "net" && !$is_net} continue
        if {$kind eq "pin" && ($is_net || [string first "/" $nm] < 0)} continue
        dict set seen $nm 1
    }
    close $fh
    if {[info exists seen]} { set out [dict keys $seen] }
    return $out
}


# --- 실제로 하는 일은 아래 네 줄이 전부 -------------------------------
puts "리포트 읽는 중 : $RPT"

set PINS [get_pins -quiet [names_in_report $RPT pin]]
redirect -file $OUTDIR/pin_attr.txt { report_attribute -application -attribute $PIN_ATTRS $PINS }
puts "  pin_attr.txt  <- 핀 [sizeof_collection $PINS] 개"

set NETS [get_nets -quiet [names_in_report $RPT net]]
redirect -file $OUTDIR/net_attr.txt { report_attribute -application -attribute $NET_ATTRS $NETS }
puts "  net_attr.txt  <- 넷 [sizeof_collection $NETS] 개"

puts ""
if {[sizeof_collection $PINS] == 0} {
    puts "=================================================================="
    puts "  문제 발생"
    puts "    무엇이   : 리포트에서 핀을 하나도 못 찾았습니다."
    puts "    하실 일  : $RPT 을 열어 보세요."
    puts "               - Error 로만 차 있으면 : 디자인이 안 올라온 것입니다."
    puts "                 (read_verilog / link_design 부터 다시)"
    puts "               - 경로는 있는데 핀 줄이 없으면 : report_timing 에"
    puts "                 -input_pins -nosplit 이 빠진 것입니다."
    puts ""
    puts "    에러 코드: E-NOPININRPT"
    puts "=================================================================="
} else {
    puts "끝났습니다. 이제 셸에서 파이썬을 실행하세요."
}
