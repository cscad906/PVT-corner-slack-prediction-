# =====================================================================
# all_xtalk_windows.tcl  --  PT 2차를 코너 폴더 전부에 돌린다
#
#   pt_shell> set XTALK_ROOT "<round2 폴더>"
#   pt_shell> source <패키지>/pt/all_xtalk_windows.tcl
#
# xtalk_windows.tcl 을 코너마다 부르는 것뿐이다. 새로 하는 일은 없다.
# 한 코너가 실패해도 멈추지 않고 끝까지 돈 뒤, 맨 아래 표로 알려 준다.
#
# 코너 하나만 다시 보고 싶으면 그 폴더에서 xtalk_windows.tcl 을 직접 돌리면 된다
# (화면이 똑같이 나온다).
# =====================================================================


# XTALK_ROOT 는 아래 wrapper 가 정해 준다.
# 직접 부르지 말고 4_all_corners.py 가 만들어 준 tcl 을 source 하세요.


if {![info exists XTALK_ROOT]} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : it is not set which directory to run over."
    puts "    action : do not source this file directly.  in the shell run"
    puts "               python3 4_all_corners.py --root <round2> --phase 2"
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

# 5b 를 돌린 코너만 대상으로 한다
set XT_LIST {}
foreach d [lsort [glob -nocomplain -directory $XTALK_ROOT -type d *]] {
    if {![file exists "$d/xtalk/victim_load_pins.txt"]} continue
    lappend XT_LIST $d
}

if {[llength $XT_LIST] == 0} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : no corner has been through 5b."
    puts "             looked in : $XTALK_ROOT/*/xtalk/victim_load_pins.txt"
    puts "    action : run this in the shell first."
    puts "               python3 4_all_corners.py --root $XTALK_ROOT --phase 1"
    puts ""
    puts "    code   : E-NO5B"
    puts "=================================================================="
    return
}

puts "running [llength $XT_LIST] corners."
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
    source "$XT_PKG/xtalk_windows.tcl"
    cd $XT_BASE
    if {[file exists "$d/xtalk/aggressor_windows.tsv"]} {
        lappend XT_DONE [list [file tail $d] "OK"]
    } else {
        lappend XT_DONE [list [file tail $d] "FAILED"]
    }
    puts ""
}

puts "===================================================================="
puts "  RESULT   by corner  (PT step 2)"
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
    puts "      source $XT_PKG/xtalk_windows.tcl"
} else {
    puts "  all OK.  next, in the shell:"
    puts "      python3 4_all_corners.py --root $XTALK_ROOT --phase 3"
}
puts "===================================================================="
