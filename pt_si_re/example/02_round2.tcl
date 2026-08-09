# =====================================================================
# 02_round2.tcl  --  2회차: 합집합 경로를 다시 측정 + 속성 뽑기
#
#   pt_shell> source example/02_round2.tcl
#
# 코너 db 를 로드한 뒤에 돌린다. 하는 일 두 가지:
#   1) 1_union.py 가 만든 fixed_paths.tcl 의 경로들을 다시 측정 -> <코너>.rpt
#   2) 그 리포트에 나오는 핀·넷의 속성      -> pin_attr.txt, net_attr.txt
#
# 코너를 바꿔 로드할 때마다 이 파일을 다시 source 한다.
# =====================================================================


### 코너마다 바꾸는 줄 -- 이거 하나 ####################################
set CORNER "tt0p8v25c_Cnom"
#######################################################################
# 폴더 이름이자 리포트 파일 이름이 된다.
# **바로 위에서 로드한 db 와 같은 코너인지** 꼭 확인할 것. 이름과 db 가
# 어긋나도 툴은 모르고 그냥 저장한다(나중에 알아낼 방법이 없다).


### 처음 한 번만 정하는 줄 -- 2개 ######################################
set FIXED  "example/round1/corners/fixed_paths.tcl"   ;# 1_union.py 가 만든 파일
set OUTTOP "example/round2"                           ;# 코너별 폴더가 생길 곳
#######################################################################
# 현장에서는 이 두 줄만 자기 경로로 바꾸면 그대로 쓸 수 있다. 예:
#   set FIXED  "/data/results/mycore_union/fixed_paths.tcl"
#   set OUTTOP "/data/results/round2"
# 상대경로면 pt_shell 의 현재 폴더(pwd) 기준이다.


# ---------------------------------------------------------------------
# 아래는 손댈 것이 없다
# ---------------------------------------------------------------------
set BASE [pwd]
set DUMP "$BASE/pt/dump_attr.tcl"

if {[file pathtype $FIXED]  eq "relative"} { set FIXED  "$BASE/$FIXED" }
if {[file pathtype $OUTTOP] eq "relative"} { set OUTTOP "$BASE/$OUTTOP" }

if {![file exists $FIXED]} {
    puts "=================================================================="
    puts "  문제 발생"
    puts "    무엇이   : fixed_paths.tcl 이 없습니다."
    puts "               찾아본 곳: $FIXED"
    puts "    하실 일  : 셸에서 1_union.py 를 먼저 돌리세요."
    puts "                 \$PY 1_union.py --dir <1회차 리포트 폴더>"
    puts "               경로가 다르면 위 FIXED 줄을 고치세요."
    puts ""
    puts "    에러 코드: E-NOFIXEDTCL"
    puts "=================================================================="
    return
}

file mkdir $OUTTOP/$CORNER
cd         $OUTTOP/$CORNER

# 두 tcl 모두 "지금 폴더" 기준이라 cd 만 해 두면 고칠 것이 없다.
source $FIXED   ;# -> <코너이름>.rpt
source $DUMP    ;# -> pin_attr.txt, net_attr.txt

cd $BASE

puts ""
puts "2회차 끝: $OUTTOP/$CORNER/"
puts "다음은 파이썬 터미널에서:"
puts "    setenv D $OUTTOP/$CORNER"
puts "    ln -s <SPEF 파일> \$D/design.spef"
puts "    \$PY 2a_cpin.py     --dir \$D"
puts "    \$PY 2b_distres.py  --dir \$D"
puts "    \$PY 2c_merge.py    --dir \$D"
puts "    \$PY 3_crosstalk.py --dir \$D --corner $CORNER"
