# =====================================================================
# all_xtalk_calc.tcl  --  PT 1차를 코너 폴더 전부에 돌린다
#
#   pt_shell> set XTALK_ROOT "<round2 폴더>"
#   pt_shell> source <패키지>/pt/all_xtalk_calc.tcl
#
# xtalk_calc.tcl 을 코너마다 부르는 것뿐이다. 새로 하는 일은 없다.
# 한 코너가 실패해도 멈추지 않고 끝까지 돈 뒤, 맨 아래 표로 알려 준다.
#
# 코너 하나만 다시 보고 싶으면 그 폴더에서 xtalk_calc.tcl 을 직접 돌리면 된다
# (화면이 똑같이 나온다).
# =====================================================================


# XTALK_ROOT / DELAY_TYPE 는 아래 wrapper 가 정해 준다.
# 직접 부르지 말고 4_all_corners.py 가 만들어 준 tcl 을 source 하세요.


if {![info exists XTALK_ROOT]} {
    puts "=================================================================="
    puts "  문제 발생"
    puts "    무엇이   : 어느 폴더를 돌지 안 정해졌습니다."
    puts "    하실 일  : 이 파일을 직접 source 하지 말고, 셸에서"
    puts "                 python3 4_all_corners.py --root <round2> --phase 1"
    puts "               를 돌리면 만들어 주는 tcl 을 source 하세요."
    puts ""
    puts "    에러 코드: E-NOXROOT"
    puts "=================================================================="
    return
}
if {![info exists DELAY_TYPE]} { set DELAY_TYPE "max" }

set XT_BASE [pwd]
set XT_PKG  [file dirname [file normalize [info script]]]

if {[file pathtype $XTALK_ROOT] eq "relative"} {
    set XTALK_ROOT "$XT_BASE/$XTALK_ROOT"
}
if {![file isdirectory $XTALK_ROOT]} {
    puts "=================================================================="
    puts "  문제 발생"
    puts "    무엇이   : 폴더가 없습니다: $XTALK_ROOT"
    puts "    하실 일  : 위 XTALK_ROOT 줄을 자기 경로로 고치세요."
    puts ""
    puts "    에러 코드: E-NOROOT"
    puts "=================================================================="
    return
}

# 5a 를 돌린 코너만 대상으로 한다
set XT_LIST {}
foreach d [lsort [glob -nocomplain -directory $XTALK_ROOT -type d *]] {
    if {![file exists "$d/xtalk/unique_contexts.tsv"]} continue
    lappend XT_LIST $d
}

if {[llength $XT_LIST] == 0} {
    puts "=================================================================="
    puts "  문제 발생"
    puts "    무엇이   : 5a 를 돌린 코너가 하나도 없습니다."
    puts "               찾아본 곳: $XTALK_ROOT/*/xtalk/unique_contexts.tsv"
    puts "    하실 일  : 셸에서 먼저 돌리세요."
    puts "                 python3 4_all_corners.py --root $XTALK_ROOT --phase 1"
    puts ""
    puts "    에러 코드: E-NO5A"
    puts "=================================================================="
    return
}

set XT_DELAY $DELAY_TYPE   ;# 코너별 tcl 에 전달. 루프가 끝나면 지운다
puts "코너 [llength $XT_LIST]개를 돕니다.  (delay_type=$DELAY_TYPE)"
puts ""

set XT_DONE {}
set XT_I 0
foreach d $XT_LIST {
    incr XT_I
    puts "--------------------------------------------------------------------"
    puts "\[$XT_I/[llength $XT_LIST]\] [file tail $d]"
    puts "--------------------------------------------------------------------"
    # 이 코너를 만들 때 쓴 db/spef 로 다시 로드한다.
    # 이게 없으면 처음 로드된 db 하나로 모든 코너를 계산해 버린다
    # (값은 나오고 화면엔 OK 로 뜬다 -- 제일 나쁜 실패).
    if {![file exists "$d/corner_info.tcl"]} {
        puts "  corner_info.tcl 이 없습니다. 이 코너는 건너뜁니다."
        puts "  (어느 db 로 만든 폴더인지 알 수 없어, 틀린 값을 만들지 않으려고 멈춥니다)"
        puts "  02_round2.tcl / 02_round2_all.tcl 로 2회차를 다시 돌리면 생깁니다."
        lappend XT_DONE [list [file tail $d] "정보없음"]
        puts ""
        continue
    }
    source "$d/corner_info.tcl"
    puts "        db   : [file tail $CI_DB]"
    puts "        spef : [file tail $CI_SPEF]"
    source "$XT_PKG/load_corner.tcl"

    cd $d
    source "$XT_PKG/xtalk_calc.tcl"
    cd $XT_BASE
    if {[file exists "$d/xtalk/context_raw.rpt"]} {
        lappend XT_DONE [list [file tail $d] "OK"]
    } else {
        lappend XT_DONE [list [file tail $d] "실패"]
    }
    puts ""
}

unset -nocomplain XT_DELAY   ;# 다음에 코너 하나만 직접 돌릴 때 영향 없게

puts "===================================================================="
puts "코너별 결과 (PT 1차)"
puts "--------------------------------------------------------------------"
set XT_BAD 0
foreach r $XT_DONE {
    puts [format "  %-30s %s" [lindex $r 0] [lindex $r 1]]
    if {[lindex $r 1] ne "OK"} { incr XT_BAD }
}
puts ""
if {$XT_BAD > 0} {
    puts "  실패 $XT_BAD 개. 그 코너만 따로 보려면:"
    puts "      cd <그 코너 폴더>"
    puts "      source $XT_PKG/xtalk_calc.tcl"
} else {
    puts "  전부 정상. 다음은 셸에서:"
    puts "      python3 4_all_corners.py --root $XTALK_ROOT --phase 2"
}
puts "===================================================================="
