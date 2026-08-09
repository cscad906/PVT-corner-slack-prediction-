# =====================================================================
# 02_round2_all.tcl  --  2회차를 코너 전부에 한 번에
#
#   pt_shell> source example/02_round2_all.tcl
#
# 코너마다 db/spef 를 새로 읽고, 합집합 경로를 다시 측정하고, 속성을 뽑는다.
# 00_setup.tcl 은 필요 없다 -- 이 파일이 코너마다 알아서 로드한다.
#
# 한 코너가 실패해도 멈추지 않고 끝까지 돈 뒤, 맨 아래 표로 알려 준다.
# 코너 하나만 다시 보고 싶으면 02_round2.tcl 로 그것만 돌리면 된다.
#
# 코너당 30초(로드) + 30초(측정) 정도 걸린다.
# =====================================================================


### 코너 목록 -- 형님이 적는 곳은 여기뿐 ###############################
# 한 줄 = {코너이름  db파일  spef파일}
#   코너이름 : 폴더 이름이자 산출물 파일 이름이 된다. db 이름과 맞추는 게 안전
#   db       : **이게 코너를 결정한다** (전압/온도/공정)
#   spef     : 배선 RC. **온도만** 맞추면 된다 (전압/공정과는 무관)
set L "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_benchmarks/deliverables/3nm/lib_db_pdk/db"
set S "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_benchmarks/deliverables/3nm/processors/BoomCoreV3/deliver/spef"

set CORNERS {}
lappend CORNERS [list TT_0p6V_25C "$L/TT_0p6V_25C_op_cond_all.db" "$S/boomcorev3_25.spef"]
lappend CORNERS [list TT_0p7V_25C "$L/TT_0p7V_25C_op_cond_all.db" "$S/boomcorev3_25.spef"]
lappend CORNERS [list TT_0p8V_25C "$L/TT_0p8V_25C_op_cond_all.db" "$S/boomcorev3_25.spef"]
#######################################################################


### 디자인 -- 코너와 무관하므로 한 번만 ################################
set CI_TOP     "BoomCore"
set CI_VERILOG "$S/boomcorev3_icc2.v"
set CI_SDC     "$S/boomcorev3.sdc"
#######################################################################


### 어디서 읽고 어디에 쓸지 ############################################
set FIXED  "example/round1/corners/fixed_paths.tcl"   ;# 1_union.py 가 만든 파일
set OUTTOP "example/round2"                           ;# 코너 폴더가 생길 곳
#######################################################################


# ---------------------------------------------------------------------
# 아래는 손댈 것이 없다
# ---------------------------------------------------------------------
set BASE [pwd]
set PKG  [file dirname [file dirname [file normalize [info script]]]]

if {[file pathtype $FIXED]  eq "relative"} { set FIXED  "$BASE/$FIXED" }
if {[file pathtype $OUTTOP] eq "relative"} { set OUTTOP "$BASE/$OUTTOP" }

if {![file exists $FIXED]} {
    puts "=================================================================="
    puts "  문제 발생"
    puts "    무엇이   : fixed_paths.tcl 이 없습니다."
    puts "               찾아본 곳: $FIXED"
    puts "    하실 일  : 셸에서 1_union.py 를 먼저 돌리세요."
    puts "                 python3 1_union.py --dir <1회차 리포트 폴더>"
    puts "               경로가 다르면 위 FIXED 줄을 고치세요."
    puts ""
    puts "    에러 코드: E-NOFIXEDTCL"
    puts "=================================================================="
    return
}

puts "코너 [llength $CORNERS]개를 돕니다."
puts ""

set R2_RESULT {}
set R2_I 0
foreach R2_ITEM $CORNERS {
    incr R2_I
    set CORNER  [lindex $R2_ITEM 0]
    set CI_DB   [lindex $R2_ITEM 1]
    set CI_SPEF [lindex $R2_ITEM 2]

    puts "--------------------------------------------------------------------"
    puts "\[$R2_I/[llength $CORNERS]\] $CORNER"
    puts "--------------------------------------------------------------------"

    if {![file exists $CI_DB]} {
        puts "        db 가 없습니다: $CI_DB"
        lappend R2_RESULT [list $CORNER "db없음"]
        puts ""
        continue
    }
    if {![file exists $CI_SPEF]} {
        puts "        spef 가 없습니다: $CI_SPEF"
        lappend R2_RESULT [list $CORNER "spef없음"]
        puts ""
        continue
    }

    source "$PKG/pt/round2_one.tcl"

    if {[file exists "$OUTTOP/$CORNER/corner_info.tcl"]} {
        lappend R2_RESULT [list $CORNER "OK"]
    } else {
        lappend R2_RESULT [list $CORNER "실패"]
    }
    puts ""
}

puts "===================================================================="
puts "코너별 결과 (2회차)"
puts "--------------------------------------------------------------------"
set R2_BAD 0
foreach r $R2_RESULT {
    puts [format "  %-30s %s" [lindex $r 0] [lindex $r 1]]
    if {[lindex $r 1] ne "OK"} { incr R2_BAD }
}
puts ""
if {$R2_BAD > 0} {
    puts "  실패 $R2_BAD 개. 위 목록의 db/spef 경로를 확인하세요."
    puts "  한 코너만 다시 보려면 02_round2.tcl 을 쓰세요."
} else {
    puts "  전부 정상. 다음은 셸에서:"
    puts "      python3 4_all_corners.py --root $OUTTOP --spef <SPEF> --phase 1"
}
puts "===================================================================="
