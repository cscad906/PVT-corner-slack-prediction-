# =====================================================================
# run_one_corner.tcl   --   PrimeTime, one corner, everything in one run.
#
#   pt_shell -f run_one_corner.tcl
#
# Edit the INPUTS block below. Nothing else needs changing.
#
# Writes 4 files and prints a PASS/FAIL verdict at the end.
# Attribute names are probed at run time, so a PrimeTime version that spells
# them differently degrades to fewer columns instead of dying.
# =====================================================================

# --------------------------------------------------------------- INPUTS
set TOP      "MyCoreTop"
set VERILOG  "/path/to/design.v"
set SDC      "/path/to/design.sdc"
set SPEF     "/path/to/design.Cnom_25.spef"
set LIB_DB   "/path/to/corner.db"
set OUTDIR   "/path/to/out"
set TAG      "tt0p65v25c_Cnom"

set DTYPE    "max"      ;# setup=max, hold=min
set NWORST   3          ;# setup=3, hold=10
set MAXPATHS 3000
set SLACK_TH 0.05       ;# SDC time unit; paths with slack < this
# =====================================================================

set OUT_RPT  "$OUTDIR/$TAG.rpt"
set OUT_MAP  "$OUTDIR/$TAG.path_map.tsv"
set OUT_NET  "$OUTDIR/$TAG.net.tsv"
set OUT_PIN  "$OUTDIR/$TAG.pin.tsv"
set OUT_PROBE "$OUTDIR/$TAG.attr_probe.txt"

# collection 을 돌려주는 attribute 만 이름 목록으로 편다. "값을 보고 collection 인지
# 추측" 하면 스칼라(0.03 같은 값)까지 collection 으로 오인해 빈 값이 되므로, 이름으로
# 명시한다.
set ::COLL_ATTRS {
  effective_aggressors aggressors
  coupling_capacitors effective_coupling_capacitors
}

proc A {obj attr} {
  if {$obj eq ""} { return "" }
  if {[catch {get_attribute -quiet $obj $attr} v]} { return "" }
  if {$v eq ""} { return "" }
  if {[lsearch -exact $::COLL_ATTRS $attr] >= 0} {
    set r {}
    if {[catch {foreach_in_collection c $v { lappend r [get_object_name $c] }}]} { return $v }
    if {[llength $r] == 0} { return "" }
    return [join $r ","]
  }
  return $v
}

# 숫자로 해석 가능하고 0 이 아니면 1.
proc NONZERO {v} {
  if {$v eq ""} { return 0 }
  if {![string is double -strict $v]} { return 0 }
  return [expr {$v != 0}]
}

proc SAFE {s} {
  return [string map {"\t" " " "\n" " " "\r" " "} $s]
}

# ------------------------------------------------------------- PREFLIGHT
foreach f [list $VERILOG $SDC $SPEF $LIB_DB] {
  if {![file exists $f]} {
    puts stderr "FATAL: missing input: $f"
    exit 1
  }
}
file mkdir $OUTDIR

# ----------------------------------------------------------------- SETUP
set_app_var si_enable_analysis true
set_app_var timing_save_pin_arrival_and_slack true

read_verilog $VERILOG
current_design $TOP
set link_path "* $LIB_DB"
link_design
read_sdc $SDC
read_parasitics -keep_capacitive_coupling $SPEF
set_propagated_clock [all_clocks]
update_timing

puts "INFO: si_enable_analysis = [get_app_var si_enable_analysis]"

# ------------------------------------------------------------ 1. TIMING
redirect -file $OUT_RPT {
  report_timing -delay_type $DTYPE -path_type full_clock_expanded \
    -nets -capacitance -transition_time -input_pins \
    -nosplit -significant_digits 4 \
    -nworst $NWORST -max_paths $MAXPATHS -slack_lesser_than $SLACK_TH
}
puts "INFO: wrote $OUT_RPT"

set paths [get_timing_paths -delay_type $DTYPE \
             -nworst $NWORST -max_paths $MAXPATHS -slack_lesser_than $SLACK_TH]
set npaths [sizeof_collection $paths]
puts "INFO: paths = $npaths"
if {$npaths == 0} {
  puts stderr "FATAL: no paths matched (slack_lesser_than $SLACK_TH). Raise SLACK_TH."
  exit 2
}

# --------------------------------------------- 2. PATH -> PIN/NET MAP
# report_attribute 계열 출력에는 경로 정보가 없다. 경로 단위 학습 행을 만들려면
# 이 매핑이 있어야 하므로 여기서 함께 뜬다.
set fh [open $OUT_MAP w]
puts $fh "path_idx\tslack\tstartpoint\tendpoint\tarc_idx\tpin\tnet"
set pidx 0
set nmap 0
array set NETSEEN {}
array set PINSEEN {}
foreach_in_collection p $paths {
  incr pidx
  set slack [A $p slack]
  set sp    [A $p startpoint]
  set ep    [A $p endpoint]
  if {$sp ne "" && [catch {set sp [get_object_name $sp]}]} { }
  if {$ep ne "" && [catch {set ep [get_object_name $ep]}]} { }
  set aidx 0
  if {[catch {set points [get_attribute $p points]}]} { continue }
  foreach_in_collection tp $points {
    if {[catch {set obj [get_attribute -quiet $tp object]}]} { continue }
    if {$obj eq ""} { continue }
    if {[catch {set pn [get_object_name $obj]}]} { continue }
    set nn ""
    if {[catch {set nn [get_nets -quiet -of_objects $obj]}]} { set nn "" }
    set netname ""
    if {$nn ne "" && ![catch {set sz [sizeof_collection $nn]}] && $sz > 0} {
      set netname [get_object_name [index_collection $nn 0]]
    }
    incr aidx
    incr nmap
    set PINSEEN($pn) 1
    if {$netname ne ""} { set NETSEEN($netname) 1 }
    puts $fh "$pidx\t$slack\t[SAFE $sp]\t[SAFE $ep]\t$aidx\t[SAFE $pn]\t[SAFE $netname]"
  }
}
close $fh
puts "INFO: wrote $OUT_MAP  (rows=$nmap)"

set netlist [array names NETSEEN]
set pinlist [array names PINSEEN]
puts "INFO: unique nets = [llength $netlist], unique pins = [llength $pinlist]"

# ------------------------------------------- 3. PROBE ATTRIBUTE NAMES
# PT 버전마다 이름이 다를 수 있으므로, 후보를 실제 객체에 한 번씩 걸어보고
# 살아남는 것만 컬럼으로 쓴다. 이름을 미리 확인할 필요가 없게 하기 위함이다.
set NET_CANDIDATES {
  annotated_delay_delta_max annotated_delay_delta_min
  number_of_aggressors number_of_effective_aggressors
  total_coupling_capacitance total_effective_coupling_capacitance
  effective_aggressors aggressors
  si_xtalk_bumps si_xtalk_bumps_max_rise si_xtalk_bumps_max_fall
  si_xtalk_bumps_min_rise si_xtalk_bumps_min_fall
  total_capacitance total_net_capacitance
}
set PIN_CANDIDATES {
  min_rise_arrival max_rise_arrival min_fall_arrival max_fall_arrival
  actual_rise_transition_max actual_fall_transition_max
  actual_rise_transition_min actual_fall_transition_min
  arrival_window max_slack min_slack
}

proc probe {objname objtype candidates} {
  set ok {}
  if {$objtype eq "net"} {
    set o [get_nets -quiet $objname]
  } else {
    set o [get_pins -quiet $objname]
  }
  if {$o eq "" || [catch {set s [sizeof_collection $o]}] || $s == 0} { return $ok }
  set obj [index_collection $o 0]
  foreach a $candidates {
    if {![catch {get_attribute -quiet $obj $a}]} { lappend ok $a }
  }
  return $ok
}

set NET_ATTRS {}
set PIN_ATTRS {}
foreach nname [lrange $netlist 0 19] {
  set NET_ATTRS [probe $nname net $NET_CANDIDATES]
  if {[llength $NET_ATTRS] > 0} { break }
}
foreach pname [lrange $pinlist 0 19] {
  set PIN_ATTRS [probe $pname pin $PIN_CANDIDATES]
  if {[llength $PIN_ATTRS] > 0} { break }
}
puts "INFO: net attrs found = [llength $NET_ATTRS] : $NET_ATTRS"
puts "INFO: pin attrs found = [llength $PIN_ATTRS] : $PIN_ATTRS"

# 이름을 하나도 못 찾은 경우를 대비해 객체 1개의 전체 attribute 를 남긴다.
# 이 파일만 보면 그 PT 버전의 실제 이름을 알 수 있다.
if {[llength $netlist] > 0} {
  redirect -file $OUT_PROBE {
    puts "### NET ATTRIBUTES"
    catch { report_attribute -application [get_nets -quiet [lindex $netlist 0]] }
    puts ""
    puts "### PIN ATTRIBUTES"
    catch { report_attribute -application [get_pins -quiet [lindex $pinlist 0]] }
  }
  puts "INFO: wrote $OUT_PROBE"
}

# ------------------------------------------------- 4. NET ATTR TABLE
set fh [open $OUT_NET w]
puts $fh "net\t[join $NET_ATTRS \t]"
set nnet 0
set n_delta_nonzero 0
foreach nm $netlist {
  set o [get_nets -quiet $nm]
  if {$o eq "" || [catch {set s [sizeof_collection $o]}] || $s == 0} { continue }
  set obj [index_collection $o 0]
  set row {}
  foreach a $NET_ATTRS {
    lappend row [SAFE [A $obj $a]]
  }
  incr nnet
  puts $fh "[SAFE $nm]\t[join $row \t]"
  if {[NONZERO [A $obj annotated_delay_delta_max]]} { incr n_delta_nonzero }
}
close $fh
puts "INFO: wrote $OUT_NET  (nets=$nnet)"

# ------------------------------------------------- 5. PIN ATTR TABLE
set fh [open $OUT_PIN w]
puts $fh "pin\t[join $PIN_ATTRS \t]"
set npin 0
set n_arr_nonempty 0
foreach pm $pinlist {
  set o [get_pins -quiet $pm]
  if {$o eq "" || [catch {set s [sizeof_collection $o]}] || $s == 0} { continue }
  set obj [index_collection $o 0]
  set row {}
  foreach a $PIN_ATTRS {
    lappend row [SAFE [A $obj $a]]
  }
  incr npin
  puts $fh "[SAFE $pm]\t[join $row \t]"
  if {[A $obj max_rise_arrival] ne ""} { incr n_arr_nonempty }
}
close $fh
puts "INFO: wrote $OUT_PIN  (pins=$npin)"

# ------------------------------------------------------------ VERDICT
puts ""
puts "======================================================================"
puts "FILES"
puts "  timing report : $OUT_RPT"
puts "  path map      : $OUT_MAP   rows=$nmap"
puts "  net table     : $OUT_NET   nets=$nnet  cols=[llength $NET_ATTRS]"
puts "  pin table     : $OUT_PIN   pins=$npin  cols=[llength $PIN_ATTRS]"
puts "  attr probe    : $OUT_PROBE"
puts "----------------------------------------------------------------------"
set fail 0
if {$nmap == 0} {
  puts "FAIL  path map is empty -- no timing points were walkable"
  set fail 1
}
if {[llength $NET_ATTRS] == 0} {
  puts "FAIL  no net attributes resolved -- send $OUT_PROBE back for name mapping"
  set fail 1
} elseif {$n_delta_nonzero == 0} {
  puts "FAIL  crosstalk delta is zero on every net"
  puts "      -> SPEF has no coupling caps (needs StarRC COUPLING_CAP: YES), or"
  puts "         parasitics were not read with -keep_capacitive_coupling"
  set fail 1
} else {
  puts "PASS  crosstalk delta nonzero on $n_delta_nonzero / $nnet nets"
}
if {[llength $PIN_ATTRS] == 0 || $n_arr_nonempty == 0} {
  puts "WARN  pin arrival attributes are empty"
  puts "      -> timing_save_pin_arrival_and_slack must be true before update_timing"
} else {
  puts "PASS  pin arrival present on $n_arr_nonempty / $npin pins"
}
puts "======================================================================"
if {$fail} { exit 3 }
exit 0
