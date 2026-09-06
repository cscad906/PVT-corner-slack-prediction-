# PrimeTime scaling 실제 실행 전용
#
# 사용자 설정은 check_scaling.tcl 위쪽에서 한 번만 수정합니다.
# 먼저 check_scaling.tcl을 source하여 선택을 확인한 뒤, 새 pt_shell에서 실행합니다.
#
#   source /home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/pt/run_scaling.tcl

set ::auto_scaling_load_only 1
source /home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/pt/check_scaling.tcl
unset ::auto_scaling_load_only

set scaling_config [auto_scaling::build_config]
set scaling_result [auto_scaling::run $scaling_config]
puts "RUN 완료: PrimeTime scaling과 fixed-path report 생성이 끝났습니다."
