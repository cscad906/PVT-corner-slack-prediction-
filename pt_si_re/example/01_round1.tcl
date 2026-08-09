# =====================================================================
# 01_round1.tcl  --  1회차: 코너마다 경로 뽑기
#
#   pt_shell> source example/01_round1.tcl
#
# 현장에서는 코너(전압/온도/RC)를 바꿔 로드할 때마다 report_timing 을 한 번씩
# 돌립니다. 이 예제는 db 를 바꾸는 대신 **경로 조건을 조금씩 달리해** 코너 3개를
# 흉내냅니다(파일 이름이 곧 코너 이름이 됩니다).
#
# 실제로는 아래 한 줄만 코너마다 반복하면 됩니다:
#   report_timing ... > round1/corners/<코너이름>.rpt
# =====================================================================

file mkdir example/round1/corners

# 코너 이름과, 그 코너에서 볼 경로 수
#   현장에서는 -max_paths 를 같은 값으로 두고 db 만 바꿉니다.
#   여기서는 db 를 안 바꾸므로 경로 수를 달리해 서로 다른 집합을 만듭니다.
foreach {name npath} {
    tt0p8v25c_Cnom 120
    tt0p7v25c_Cnom 200
    tt0p6v25c_Cnom 300
} {
    set out "example/round1/corners/$name.rpt"
    redirect -file $out {
        report_timing -delay_type max -path_type full_clock_expanded \
          -nets -input_pins -nosplit -significant_digits 6 \
          -nworst 3 -max_paths $npath -slack_lesser_than 0.05
    }
    puts "  $name  -> $out"
}

puts ""
puts "1회차 끝. 다음은 셸에서:"
puts "    python3 1_union.py --dir example/round1/corners"
