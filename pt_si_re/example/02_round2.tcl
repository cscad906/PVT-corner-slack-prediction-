# =====================================================================
# 02_round2.tcl  --  2회차, 코너 하나만
#
#   pt_shell> source example/02_round2.tcl
#
# 코너를 여러 개 할 거면 02_round2_all.tcl 을 쓰세요. 이건 한 코너가
# 실패했을 때 그것만 다시 볼 때 씁니다.
#
# 00_setup.tcl 은 필요 없습니다 -- 이 파일이 db/spef 를 직접 읽습니다.
# =====================================================================


### 이 코너 -- 세 줄 ###################################################
set L "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_benchmarks/deliverables/3nm/lib_db_pdk/db"
set S "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_benchmarks/deliverables/3nm/processors/BoomCoreV3/deliver/spef"

set CORNER  "TT_0p6V_25C"                        ;# 폴더 이름이자 산출물 이름
set CI_DB   "$L/TT_0p6V_25C_op_cond_all.db"      ;# **이게 코너를 결정한다**
set CI_SPEF "$S/boomcorev3_25.spef"              ;# 배선 RC. 온도만 맞추면 된다
#######################################################################


### 디자인 -- 코너와 무관 ##############################################
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
    puts "  PROBLEM"
    puts "    what   : fixed_paths.tcl is missing."
    puts "             looked in : $FIXED"
    puts "    action : run 1_union.py in the shell first."
    puts "               python3 1_union.py --dir <round 1 report dir>"
    puts ""
    puts "    code   : E-NOFIXEDTCL"
    puts "=================================================================="
    return
}
foreach f [list $CI_DB $CI_SPEF $CI_VERILOG $CI_SDC] {
    if {![file exists $f]} {
        puts "=================================================================="
        puts "  PROBLEM"
        puts "    what   : file does not exist: $f"
        puts "    action : check the path lines above."
        puts ""
        puts "    code   : E-NOINPUTFILE"
        puts "=================================================================="
        return
    }
}

puts "--------------------------------------------------------------------"
puts "$CORNER"
puts "--------------------------------------------------------------------"

source "$PKG/dev/round2_one.tcl"

puts ""
puts "round 2 done: $OUTTOP/$CORNER/"
puts "next, in the shell:"
puts "    python3 4_all_corners.py --root $OUTTOP --spef <SPEF> --phase 1"
