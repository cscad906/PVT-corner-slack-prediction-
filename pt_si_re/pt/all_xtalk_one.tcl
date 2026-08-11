# =====================================================================
# all_xtalk_one.tcl  --  crosstalk PT 를 코너 폴더 전부에 (한 번에 끝)
#
#   pt_shell> set XTALK_ROOT "<round2 폴더>"
#   pt_shell> source <패키지>/pt/all_xtalk_one.tcl
#
# xtalk_all.tcl 을 코너마다 부르는 것뿐이다. 새로 하는 일은 없다.
# 한 코너가 실패해도 멈추지 않고 끝까지 돈 뒤, 맨 아래 표로 알려 준다.
#
# 코너 하나만 다시 보고 싶으면 그 폴더에서 xtalk_all.tcl 을 직접 돌리면 된다
# (화면이 똑같이 나온다).
# =====================================================================


# XTALK_ROOT / DELAY_TYPE 는 아래 wrapper 가 정해 준다.
# 직접 부르지 말고 4_all_corners.py 가 만들어 준 tcl 을 source 하세요.


if {![info exists XTALK_ROOT]} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : it is not set which directory to run over."
    puts "    action : do not source this file directly.  in the shell run"
    puts "               python3 4_all_corners.py --root <round2> --phase 1"
    puts "             and source the tcl it writes for you."
    puts ""
    puts "    code   : E-NOXROOT"
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
    puts "  PROBLEM"
    puts "    what   : directory does not exist: $XTALK_ROOT"
    puts "    action : fix the XTALK_ROOT line above to your own path."
    puts ""
    puts "    code   : E-NOROOT"
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
    puts "  PROBLEM"
    puts "    what   : no corner has been through 5a."
    puts "             looked in : $XTALK_ROOT/*/xtalk/unique_contexts.tsv"
    puts "    action : run this in the shell first."
    puts "               python3 4_all_corners.py --root $XTALK_ROOT --phase 1"
    puts ""
    puts "    code   : E-NO5A"
    puts "=================================================================="
    return
}

# 앞서 코너 하나를 직접 돌리며 XT_RPT 를 줬다면 그 값이 세션에 남아 있다.
# 여기서는 코너마다 5a 가 만든 목록을 쓰므로 남은 값이 끼어들지 않게 지운다.
unset -nocomplain XT_RPT XT_DIR

set XT_DELAY $DELAY_TYPE   ;# 코너별 tcl 에 전달. 루프가 끝나면 지운다
puts "running [llength $XT_LIST] corners.  (delay_type=$DELAY_TYPE)"
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
        puts "  no corner_info.tcl here.  this corner is skipped."
        puts "  (the db it was made with is unknown, so it is skipped rather"
        puts "   than producing wrong numbers)"
        puts "  re-run round 2 (02_round2.tcl / 02_round2_all.tcl) to create it."
        lappend XT_DONE [list [file tail $d] "NO INFO"]
        puts ""
        continue
    }
    source "$d/corner_info.tcl"
    puts "        db   : [file tail $CI_DB]"
    puts "        spef : [file tail $CI_SPEF]"
    source "$XT_PKG/load_corner.tcl"

    cd $d
    source "$XT_PKG/xtalk_all.tcl"
    cd $XT_BASE
    if {[file exists "$d/xtalk/aggressor_windows.tsv"]} {
        lappend XT_DONE [list [file tail $d] "OK"]
    } else {
        lappend XT_DONE [list [file tail $d] "FAILED"]
    }
    puts ""
}

unset -nocomplain XT_DELAY   ;# 다음에 코너 하나만 직접 돌릴 때 영향 없게

puts "===================================================================="
puts "  RESULT   by corner  (crosstalk PT)"
puts "--------------------------------------------------------------------"
set XT_BAD 0
foreach r $XT_DONE {
    puts [format "  %-30s %s" [lindex $r 0] [lindex $r 1]]
    if {[lindex $r 1] ne "OK"} { incr XT_BAD }
}
puts ""
if {$XT_BAD > 0} {
    puts "  $XT_BAD failed.  to run just that corner:"
    puts "      cd <that corner directory>"
    puts "      source $XT_PKG/xtalk_all.tcl"
} else {
    puts "  all OK.  next, in the shell:"
    puts "      python3 4_all_corners.py --root $XTALK_ROOT --phase 2"
}
puts "===================================================================="
