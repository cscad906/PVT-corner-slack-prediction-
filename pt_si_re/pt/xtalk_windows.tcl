# =====================================================================
# xtalk_windows.tcl  --  crosstalk 쌍 리포트 4단계 (PT 2차)
#
#   pt_shell> cd <코너폴더>
#   pt_shell> source <패키지>/pt/xtalk_windows.tcl
#
# 5b_pairs.py 가 뽑아 놓은 두 목록에 대해 도착시각/기울기를 뽑는다.
#   victim_load_pins.txt  -> 그 핀이 언제 도착하는지
#   aggressor_nets.txt    -> 그 넷의 driver 핀 + 언제 도착하는지 + slew
#
# 왜 또 PT 인가: aggressor 는 우리 경로에 없는 남의 넷이라 pin_attr.txt 에
# 안 들어 있다. crosstalk 은 victim 과 aggressor 가 **같은 시점에 움직일 때만**
# 실제 영향이 있으므로, 그 판단 재료로 양쪽 도착시각이 필요하다.
#
# 디자인은 이미 로드되어 있다고 본다.
# =====================================================================


### 여기 한 줄만 고치면 된다 ###########################################
set XTALK_DIR "xtalk"     ;# 지금 폴더 아래의 xtalk/ (코너 폴더로 cd 해 두면 그대로)
#######################################################################


set VPIN "$XTALK_DIR/victim_load_pins.txt"
set ANET "$XTALK_DIR/aggressor_nets.txt"
set VOUT "$XTALK_DIR/victim_windows.tsv"
set AOUT "$XTALK_DIR/aggressor_windows.tsv"

if {[sizeof_collection [get_designs -quiet *]] == 0} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : no design is loaded in PrimeTime."
    puts "    action : read netlist / library / SDC / SPEF first."
    puts ""
    puts "    code   : E-NODESIGN"
    puts "=================================================================="
    return
}
if {![file exists $VPIN] || ![file exists $ANET]} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : the lists to query are missing."
    puts "             looked in : $VPIN"
    puts "                         $ANET"
    puts "    action : run 5b_pairs.py in the shell first."
    puts "               python3 5b_pairs.py --dir <corner dir>"
    puts ""
    puts "    code   : E-NOWINLIST"
    puts "=================================================================="
    return
}


# --- 이 폴더가 어느 db 로 만들어졌는지 확인 --------------------------
# 루프(all_*.tcl)로 왔으면 이미 그 db 로 로드된 상태다. 사람이 이 파일만
# 직접 돌릴 때는 지금 올라온 디자인이 이 폴더의 코너가 맞는지 알 수 없으므로,
# 기록을 읽어 화면에 찍어 준다. 다르면 멈추고 다시 로드할 것.
if {[file exists "corner_info.tcl"]} {
    source "corner_info.tcl"
    puts "  corner of this directory : $CI_CORNER"
    puts "  db it expects            : $CI_DB"
    puts "  (if the db now loaded in PT is not this one, stop and load it again)"
} else {
    puts "  WARNING: no corner_info.tcl, so the db this directory was made with"
    puts "           is unknown.  the db now loaded will be used.  check the"
    puts "           corner yourself."
}

# --- 여기부터는 값 꺼내는 잔일이라 안 봐도 된다 -----------------------
proc xt_clean {s} {
    return [string map {"\t" " " "\n" " " "\r" " "} $s]
}

proc xt_attr {obj name} {
    set v ""
    if {[catch {set v [get_attribute -quiet $obj $name]}]} { return "" }
    return $v
}

proc xt_pick {vals want} {
    # want = min 또는 max. 빈 값은 건너뛴다.
    set best ""
    foreach v $vals {
        if {$v eq ""} continue
        if {$best eq ""} { set best $v ; continue }
        if {$want eq "min" && $v < $best} { set best $v }
        if {$want eq "max" && $v > $best} { set best $v }
    }
    return $best
}

proc xt_window {pin_name} {
    set pin [get_pins -quiet $pin_name]
    if {[sizeof_collection $pin] == 0} {
        return [list [xt_clean $pin_name] "" "" "" "" "" "" "" "PIN_NOT_FOUND"]
    }
    set mnr [xt_attr $pin min_rise_arrival]
    set mxr [xt_attr $pin max_rise_arrival]
    set mnf [xt_attr $pin min_fall_arrival]
    set mxf [xt_attr $pin max_fall_arrival]
    set slr [xt_attr $pin actual_rise_transition_max]
    set slf [xt_attr $pin actual_fall_transition_max]
    return [list [xt_clean $pin_name] \
                 [xt_pick [list $mnr $mnf] min] \
                 [xt_pick [list $mxr $mxf] max] \
                 $mnr $mxr $mnf $mxf \
                 [xt_pick [list $slr $slf] max] "OK"]
}

proc xt_driver {net_name} {
    set net [get_nets -quiet $net_name]
    if {[sizeof_collection $net] == 0} { return "" }
    set pins ""
    if {[catch {
        set pins [get_pins -quiet -leaf -of_objects $net \
                    -filter "direction == out || direction == inout"]
    }] || [sizeof_collection $pins] == 0} {
        set pins [get_pins -quiet -of_objects $net \
                    -filter "direction == out || direction == inout"]
    }
    if {[sizeof_collection $pins] == 0} { return "" }
    return [get_object_name [index_collection $pins 0]]
}


# --- victim 쪽 -------------------------------------------------------
set fh [open $VPIN r]
set out [open $VOUT w]
puts $out "victim_load_pin\tvictim_load_min_arrival\tvictim_load_max_arrival\tmin_rise\tmax_rise\tmin_fall\tmax_fall\tslew_max\tstatus"
set nv 0
set nv_bad 0
while {[gets $fh line] >= 0} {
    set p [string trim $line]
    if {$p eq ""} continue
    incr nv
    set row [xt_window $p]
    if {[lindex $row end] ne "OK"} { incr nv_bad }
    puts $out [join $row "\t"]
}
close $fh
close $out
puts "  victim pins    : $nv  (not found $nv_bad)"


# --- aggressor 쪽 ----------------------------------------------------
set fh [open $ANET r]
set out [open $AOUT w]
puts $out "aggressor_net\taggressor_driver_pin\taggressor_driver_min_arrival\taggressor_driver_max_arrival\tmin_rise\tmax_rise\tmin_fall\tmax_fall\taggressor_driver_slew_max\tstatus"
set na 0
set na_bad 0
while {[gets $fh line] >= 0} {
    set n [string trim $line]
    if {$n eq ""} continue
    incr na
    set drv [xt_driver $n]
    if {$drv eq ""} {
        incr na_bad
        puts $out "[xt_clean $n]\t\t\t\t\t\t\t\t\tNO_DRIVER"
        continue
    }
    set row [xt_window $drv]
    if {[lindex $row end] ne "OK"} { incr na_bad }
    puts $out "[xt_clean $n]\t[join $row "\t"]"
}
close $fh
close $out
puts "  aggressor nets : $na  (no driver $na_bad)"

puts ""
if {$nv == 0 && $na == 0} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : there was nothing to query (0 items)."
    puts "    action : check the counts printed by 5b_pairs.py -- the line"
    puts "             that says how many pins / nets it will ask about."
    puts ""
    puts "    code   : E-NOWIN"
    puts "=================================================================="
    return
}

puts "finished.  next, in the shell:"
puts "    python3 5c_report.py --dir <corner dir>"
