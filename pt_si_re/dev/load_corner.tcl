# =====================================================================
# load_corner.tcl  --  코너 하나를 PT 에 올린다 (다른 tcl 이 부르는 부품)
#
# 이 파일을 직접 source 할 일은 없다. 아래 넷이 부른다.
#     02_round2.tcl / 02_round2_all.tcl        (2회차)
#     all_xtalk_one.tcl                          (crosstalk PT 단계)
#
# 부르기 전에 CI_TOP / CI_VERILOG / CI_SDC / CI_DB / CI_SPEF 를 정해 둔다.
#
# 왜 통째로 다시 읽는가
#   PT 는 이미 링크된 디자인에 다른 라이브러리를 못 붙인다 (DES-067).
#   그래서 코너를 바꾸려면 remove_design 부터 해야 한다. 28초쯤 걸린다.
# =====================================================================

set_app_var si_enable_analysis true
set_app_var timing_save_pin_arrival_and_slack true

remove_design -all
read_verilog   $CI_VERILOG
current_design $CI_TOP
set link_path  "* $CI_DB"
link_design
read_sdc       $CI_SDC
read_parasitics -keep_capacitive_coupling $CI_SPEF
set_propagated_clock [all_clocks]
update_timing
