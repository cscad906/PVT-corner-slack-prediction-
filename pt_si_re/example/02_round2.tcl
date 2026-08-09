# =====================================================================
# 02_round2.tcl  --  2회차: 합집합 경로를 다시 측정 + 속성 뽑기
#
#   pt_shell> source example/02_round2.tcl
#
# 하는 일 두 가지
#   1) 1_union.py 가 만든 fixed_paths.tcl 을 읽어 **같은 경로들**을 다시 측정
#   2) 그 리포트에 나오는 핀·넷의 속성을 pin_attr.txt / net_attr.txt 로 저장
#
# 현장에서는 코너를 바꿔 로드할 때마다 이 두 단계를 반복한다.
# =====================================================================

set BASE  [pwd]
set FIXED "$BASE/example/round1/corners/fixed_paths.tcl"

if {![file exists $FIXED]} {
    puts "ERROR: $FIXED 가 없습니다."
    puts "       먼저 셸에서 1_union.py 를 돌리세요:"
    puts "         \$PY 1_union.py --dir example/round1/corners"
    return
}

# 코너 이름 = 결과가 쌓일 폴더 이름. 코너마다 이 한 줄만 바꾼다.
set CORNER "tt0p7v25c_Cnom"

file mkdir $BASE/example/round2/$CORNER
cd        $BASE/example/round2/$CORNER

# 두 tcl 모두 기본값이 "지금 폴더"라, cd 만 해 두면 고칠 것이 없다.
source $FIXED                  ;# -> timing.rpt
source $BASE/pt/dump_attr.tcl  ;# -> pin_attr.txt, net_attr.txt

cd $BASE

puts ""
puts "2회차 끝: example/round2/$CORNER/"
puts "다음은 셸에서 (D=example/round2/$CORNER):"
puts "    \$PY 2a_cpin.py     --dir \$D"
puts "    \$PY 2b_distres.py  --dir \$D --spef <SPEF 파일>"
puts "    \$PY 2c_merge.py    --dir \$D"
puts "    \$PY 3_crosstalk.py --dir \$D --corner $CORNER"
