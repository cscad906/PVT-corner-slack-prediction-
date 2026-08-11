# =====================================================================
# round2_one.tcl  --  코너 하나의 2회차 (다른 tcl 이 부르는 부품)
#
# 이 파일을 직접 source 할 일은 없다.
#     02_round2.tcl      코너 하나만 할 때
#     02_round2_all.tcl  코너 목록을 한 번에 돌 때
# 둘 다 이걸 부른다.
#
# 부르기 전에 정해 둘 것
#     CORNER  CI_TOP  CI_VERILOG  CI_SDC  CI_DB  CI_SPEF  FIXED  OUTTOP  PKG
#
# 하는 일
#   1) 그 코너의 db/spef 로 디자인을 올린다        (load_corner.tcl)
#   2) 합집합 경로를 다시 측정                      -> <코너>.rpt
#   3) 그 리포트의 핀/넷 속성                       -> pin_attr.txt, net_attr.txt
#   4) **무엇으로 만들었는지 기록**                 -> corner_info.tcl
#
# 4가 중요하다. crosstalk 단계는 나중에 따로 도는데, 그때는 이 폴더가 어느
# db 로 만들어졌는지 알 방법이 없다. 그걸 모르면 처음 로드된 db 하나로 모든
# 코너를 계산해 버린다(값은 나오고 화면엔 OK 로 뜬다 -- 제일 나쁜 실패).
# =====================================================================

set R2_DIR "$OUTTOP/$CORNER"

puts "        db   : [file tail $CI_DB]"
puts "        spef : [file tail $CI_SPEF]"

# --- 1) 디자인 로드 --------------------------------------------------
source "$PKG/dev/load_corner.tcl"

# --- 2) + 3) 측정 ----------------------------------------------------
file mkdir $R2_DIR
cd         $R2_DIR
source $FIXED        ;# -> <코너>.rpt
source "$PKG/dev/dump_attr.tcl"   ;# -> pin_attr.txt, net_attr.txt
cd $BASE

# --- 4) 무엇으로 만들었는지 남긴다 -----------------------------------
set fh [open "$R2_DIR/corner_info.tcl" w]
puts $fh "# settings used to make this directory.  auto-generated -- do not edit."
puts $fh "# the crosstalk step reads this and loads the same db again."
puts $fh "# without this file that corner is skipped (to avoid wrong numbers)."
puts $fh ""
puts $fh "set CI_CORNER  \"$CORNER\""
puts $fh "set CI_TOP     \"$CI_TOP\""
puts $fh "set CI_VERILOG \"$CI_VERILOG\""
puts $fh "set CI_SDC     \"$CI_SDC\""
puts $fh "set CI_DB      \"$CI_DB\""
puts $fh "set CI_SPEF    \"$CI_SPEF\""
close $fh
puts "        record : $R2_DIR/corner_info.tcl"
