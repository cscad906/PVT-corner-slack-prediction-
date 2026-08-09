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
    puts "  문제 발생"
    puts "    무엇이   : PT 에 디자인이 안 올라와 있습니다."
    puts "    하실 일  : 넷리스트/라이브러리/SDC/SPEF 를 먼저 읽으세요."
    puts ""
    puts "    에러 코드: E-NODESIGN"
    puts "=================================================================="
    return
}
if {![file exists $CTX]} {
    puts "=================================================================="
    puts "  문제 발생"
    puts "    무엇이   : 넷 목록이 없습니다."
    puts "               찾아본 곳: $CTX"
    puts "    하실 일  : 셸에서 5a_contexts.py 를 먼저 돌리세요."
    puts "                 \$PY 5a_contexts.py --dir <코너폴더>"
    puts "               폴더가 다르면 위 XTALK_DIR 줄을 고치세요."
    puts ""
    puts "    에러 코드: E-NOCTXFILE"
    puts "=================================================================="
    return
}
if {![get_app_var si_enable_analysis]} {
    puts "  주의: si_enable_analysis 가 꺼져 있습니다. crosstalk 이 전부 0 이 됩니다."
    puts "        set_app_var si_enable_analysis true  후 update_timing 하고 다시 하세요."
}


# --- 이 폴더가 어느 db 로 만들어졌는지 확인 --------------------------
# 루프(all_*.tcl)로 왔으면 이미 그 db 로 로드된 상태다. 사람이 이 파일만
# 직접 돌릴 때는 지금 올라온 디자인이 이 폴더의 코너가 맞는지 알 수 없으므로,
# 기록을 읽어 화면에 찍어 준다. 다르면 멈추고 다시 로드할 것.
if {[file exists "corner_info.tcl"]} {
    source "corner_info.tcl"
    puts "  이 폴더의 코너 : $CI_CORNER"
    puts "  기대하는 db    : $CI_DB"
    puts "  (지금 PT 에 올라온 db 가 이것이 아니면 멈추고 다시 로드하세요)"
} else {
    puts "  주의: corner_info.tcl 이 없어 어느 db 로 만든 폴더인지 알 수 없습니다."
    puts "        지금 올라온 db 로 계산합니다. 코너가 맞는지 직접 확인하세요."
}

# --- 탭 등을 없애 한 줄로 만든다 (내용은 안 봐도 된다) -----------------
proc xt_clean {s} {
    return [string map {"\t" " " "\n" " " "\r" " "} $s]
}


puts "  목록 읽는 중 : $CTX"

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
        puts "    ... $total 개 (정상 $ok / 실패 $err)"
        flush $rf
    }
}
close $cf
close $rf

puts ""
puts "  물어본 넷 : $total"
puts "  정상      : $ok"
puts "  실패      : $err"
puts "  결과 파일 : $RAW"

if {$ok == 0} {
    puts ""
    puts "=================================================================="
    puts "  문제 발생"
    puts "    무엇이   : 한 넷도 계산이 안 됐습니다."
    puts "    하실 일  : $RAW 을 열어 message= 줄을 보세요."
    puts "               PIN_NOT_FOUND 가 많으면 이 코너의 넷리스트가"
    puts "               annotated.txt 를 만든 코너와 다른 것입니다."
    puts ""
    puts "    에러 코드: E-XCALC0"
    puts "=================================================================="
    return
}

puts ""
puts "끝났습니다. 다음은 셸에서:"
puts "    \$PY 5b_pairs.py --dir <코너폴더>"
