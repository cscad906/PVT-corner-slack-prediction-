# =====================================================================
# xtalk_calc.tcl  --  crosstalk 쌍 리포트 2단계 (PT 1차)
#
#   pt_shell> cd <코너폴더>
#   pt_shell> source <패키지>/pt/xtalk_calc.tcl
#
# 5a_contexts.py 가 만든 목록의 넷마다
#     report_delay_calculation -crosstalk -from <driver> -to <load>
# 를 돌려 그 출력을 파일 하나에 모은다.
#
# 여기서 나오는 것이 aggressor **하나하나**의 bump 와 coupling cap 이다.
# report_attribute 로는 합계밖에 안 나온다.
#
# 디자인은 이미 로드되어 있다고 본다(02_round2.tcl 을 돌린 그 세션).
# =====================================================================


### 여기 두 줄만 고치면 된다 ###########################################
set XTALK_DIR  "xtalk"    ;# 지금 폴더 아래의 xtalk/ (코너 폴더로 cd 해 두면 그대로)
set DELAY_TYPE "max"      ;# setup=max, hold=min
if {[info exists XT_DELAY]} { set DELAY_TYPE $XT_DELAY }  ;# 루프가 준 값이 있으면 그것
#######################################################################
# 조건 없이 set 한다(일부러). if {![info exists ...]} 로 두면 코너를 바꿔
# 두 번째로 source 할 때 앞 코너의 값이 남아 엉뚱한 폴더에 쓴다.
# 밖에서 지정하려면 이 파일을 source 하기 전이 아니라, 위 줄을 고쳐야 한다.


set CTX "$XTALK_DIR/unique_contexts.tsv"
set RAW "$XTALK_DIR/context_raw.rpt"

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
if {![file exists $CTX]} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : the net list is missing."
    puts "             looked in : $CTX"
    puts "    action : run 5a_contexts.py in the shell first."
    puts "               python3 5a_contexts.py --dir <corner dir>"
    puts "             if the directory differs, fix the XTALK_DIR line above."
    puts ""
    puts "    code   : E-NOCTXFILE"
    puts "=================================================================="
    return
}
if {![get_app_var si_enable_analysis]} {
    puts "  WARNING: si_enable_analysis is OFF. all crosstalk values will be 0."
    puts "           do  set_app_var si_enable_analysis true , then update_timing,"
    puts "           then run this again."
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

# --- 탭 등을 없애 한 줄로 만든다 (내용은 안 봐도 된다) -----------------
proc xt_clean {s} {
    return [string map {"\t" " " "\n" " " "\r" " "} $s]
}


puts "  reading net list : $CTX"

set cf [open $CTX r]
gets $cf header
set rf [open $RAW w]

set total 0
set ok 0
set err 0
while {[gets $cf line] >= 0} {
    if {[string trim $line] eq ""} continue
    incr total

    set fields [split $line "\t"]
    set cid    [lindex $fields 0]
    set victim [lindex $fields 1]
    set driver [lindex $fields 2]
    set load   [lindex $fields 3]

    set status "OK"
    set message ""
    set text ""

    set from_obj [get_pins -quiet $driver]
    set to_obj   [get_pins -quiet $load]

    if {[sizeof_collection $from_obj] == 0} {
        set status "ERROR" ; set message "DRIVER_PIN_NOT_FOUND"
    } elseif {[sizeof_collection $to_obj] == 0} {
        set status "ERROR" ; set message "LOAD_PIN_NOT_FOUND"
    } else {
        set rc [catch {
            redirect -variable text {
                report_delay_calculation -crosstalk -$DELAY_TYPE \
                    -from $from_obj -to $to_obj
            }
        } e]
        if {$rc != 0} { set status "ERROR" ; set message $e }
    }

    if {$status eq "OK"} { incr ok } else { incr err }

    puts $rf "### PATH_CONTEXT_BEGIN"
    puts $rf "### context_id=[xt_clean $cid]"
    puts $rf "### victim_net=[xt_clean $victim]"
    puts $rf "### victim_driver_pin=[xt_clean $driver]"
    puts $rf "### victim_load_pin=[xt_clean $load]"
    puts $rf "### status=[xt_clean $status]"
    puts $rf "### message=[xt_clean $message]"
    if {$text ne ""} { puts $rf $text }
    puts $rf "### PATH_CONTEXT_END"

    if {[expr {$total % 200}] == 0} {
        puts "    ... $total done (ok $ok / fail $err)"
        flush $rf
    }
}
close $cf
close $rf

puts ""
puts "  nets queried : $total"
puts "  ok           : $ok"
puts "  failed       : $err"
puts "  output file  : $RAW"

if {$ok == 0} {
    puts ""
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : not a single net could be calculated."
    puts "    action : open $RAW and read the 'message=' lines."
    puts "             many PIN_NOT_FOUND means this corner's netlist is not"
    puts "             the one that annotated.txt was made with."
    puts ""
    puts "    code   : E-XCALC0"
    puts "=================================================================="
    return
}

puts ""
puts "finished.  next, in the shell:"
puts "    python3 5b_pairs.py --dir <corner dir>"
