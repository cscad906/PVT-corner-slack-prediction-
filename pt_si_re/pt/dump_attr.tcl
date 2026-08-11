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


### 여기 두 줄만 고치면 된다 ###########################################
set OUTDIR "."      ;# 결과(pin_attr.txt/net_attr.txt)를 저장할 폴더
set RPT    ""       ;# 읽을 리포트. 비워 두면 위 폴더의 .rpt 를 자동으로 찾는다
#######################################################################
# 기본값은 "지금 있는 폴더". 그 코너 폴더로 cd 해 두었으면 안 고쳐도 된다.
#     cd /data/round2/tt0p7v25c_Cnom   ->   source dump_attr.tcl
# 리포트가 다른 곳에 있으면 위 RPT 에 파일 경로를 직접 적는다.
#
# 두 줄 다 조건 없이 set 한다(일부러 그렇게 뒀다). if {![info exists ...]} 로
# 두면 코너를 바꿔 두 번째로 source 할 때 앞 코너의 값이 그대로 남아, 조용히
# 엉뚱한 파일을 읽거나 아무것도 안 만든다.

# --- RPT 를 비워 뒀으면 이 폴더의 .rpt 를 찾는다 ----------------------
if {$RPT eq ""} {
    set _cands [lsort [glob -nocomplain -directory $OUTDIR *.rpt]]
    if {[llength $_cands] == 1} { set RPT [lindex $_cands 0] }
    if {[llength $_cands] > 1} {
        puts "=================================================================="
        puts "  PROBLEM"
        puts "    what   : this directory has [llength $_cands] .rpt files, so"
        puts "             it is not clear which one to read."
        puts "             $_cands"
        puts "    action : write the file to read on the RPT line at the top."
        puts "             keeping one directory per corner avoids this."
        puts ""
        puts "    code   : E-RPTMANY"
        puts "=================================================================="
        return
    }
}

if {$RPT eq "" || ![file exists $RPT]} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : no report (.rpt) was found to read."
    puts "             looked in : $OUTDIR"
    puts "    action : run round 2 first ->  source fixed_paths.tcl"
    puts "             if the report is elsewhere, do  set RPT \"<file>\"  and retry."
    puts ""
    puts "    code   : E-NORPTFILE"
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
puts "reading report : $RPT"

set PINS [get_pins -quiet [names_in_report $RPT pin]]
redirect -file $OUTDIR/pin_attr.txt { report_attribute -application -attribute $PIN_ATTRS $PINS }
puts "  pin_attr.txt  <- [sizeof_collection $PINS] pins"

set NETS [get_nets -quiet [names_in_report $RPT net]]
redirect -file $OUTDIR/net_attr.txt { report_attribute -application -attribute $NET_ATTRS $NETS }
puts "  net_attr.txt  <- [sizeof_collection $NETS] nets"

puts ""
if {[sizeof_collection $PINS] == 0} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : not a single pin was found in the report."
    puts "    action : open $RPT and look at it."
    puts "             - if it is only Error lines : no design is loaded."
    puts "               (start again from read_verilog / link_design)"
    puts "             - if paths are there but no pin lines : report_timing"
    puts "               was missing -input_pins -nosplit."
    puts ""
    puts "    code   : E-NOPININRPT"
    puts "=================================================================="
} else {
    puts "finished.  now run the python steps in the shell."
}
