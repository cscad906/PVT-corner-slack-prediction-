# =====================================================================
# 00_setup.tcl  --  PT 세션 준비 (현장에서는 담당자가 해두는 부분)
#
#   pt_shell> source example/00_setup.tcl
#
# 여기서 디자인/SDC/SPEF/db 를 읽고 타이밍을 계산한다.
# 1~2분 걸린다. 한 번만 하면 된다.
# =====================================================================

set D "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_benchmarks/deliverables/3nm"

# crosstalk 를 뽑으려면 SI 를 켜야 한다
set_app_var si_enable_analysis true
# 핀별 arrival 을 뽑으려면 켜야 한다 (안 켜면 값이 전부 빈다)
set_app_var timing_save_pin_arrival_and_slack true

read_verilog   "$D/processors/BoomCoreV3/deliver/spef/boomcorev3_icc2.v"
current_design BoomCore
set link_path  "* $D/lib_db_pdk/db/TT_0p7V_25C_op_cond_all.db"
link_design
read_sdc       "$D/processors/BoomCoreV3/deliver/spef/boomcorev3.sdc"

# coupling 을 유지해야 crosstalk 값이 나온다
read_parasitics -keep_capacitive_coupling \
  "$D/processors/BoomCoreV3/deliver/spef/boomcorev3_25.spef"

set_propagated_clock [all_clocks]
update_timing

puts ""
puts "setup done.  next: source example/01_round1.tcl"
