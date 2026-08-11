# =====================================================================
# xtalk_all.tcl  --  crosstalk PT 작업을 **한 번에** (PT 1차 + 2차 합침)
#
#   pt_shell> cd <코너폴더>
#   pt_shell> source <패키지>/pt/xtalk_all.tcl
#
# 원래는 PT 를 두 번 다녀와야 했다.
#     PT 1차  넷마다 report_delay_calculation
#     (파이썬) 그 출력에서 aggressor 넷 이름을 뽑음
#     PT 2차  그 넷들의 driver 도착시각/slew
#
# 두 번째 목록을 첫 번째 출력에서 뽑아내야 해서 중간에 파이썬이 끼었다.
# 이 파일은 **tcl 이 자기가 방금 받은 출력에서 직접** aggressor 이름을 긁어
# 이어서 처리하므로, PT 를 한 번만 다녀오면 된다.
#
# 넉넉히 긁어도 안전하다: 결과 표는 이름으로 찾아 쓰는 사전이라, 안 쓰는
# 항목이 몇 개 더 있어도 최종 리포트는 달라지지 않는다.
#
# 디자인은 이미 로드되어 있다고 본다.
#
# 화면 출력은 전부 영어(ASCII)다. pt_shell 이 한글을 깨뜨리는 환경이 있어서
# 일부러 그렇게 했다. 이 주석들은 화면에 안 나오므로 한글 그대로 둔다.
# =====================================================================


### 여기 세 줄만 고치면 된다 ###########################################
set RPT_FILE   ""         ;# 읽을 리포트. **절대경로로 박아도 된다.**
                           # 비워 두면 자동으로 찾는다(아래 순서).
set XTALK_DIR  "xtalk"    ;# 결과를 쓸 폴더. 지금 폴더 아래의 xtalk/
set DELAY_TYPE "max"      ;# setup=max, hold=min
#######################################################################
if {[info exists XT_DELAY]} { set DELAY_TYPE $XT_DELAY }  ;# 루프가 준 값이 있으면 그것
if {[info exists XT_RPT]}   { set RPT_FILE   $XT_RPT   }  ;# 위 RPT_FILE 을 안 고치고
if {[info exists XT_DIR]}   { set XTALK_DIR  $XT_DIR   }  ;# 밖에서 넘기고 싶을 때 쓴다
                                                          #   set XT_RPT "/data/.../<코너>.rpt"
                                                          #   source .../xtalk_all.tcl


set CTX  "$XTALK_DIR/unique_contexts.tsv"
set RAW  "$XTALK_DIR/context_raw.rpt"
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
# 넷 목록(unique_contexts.tsv)이 없으면 아래에서 리포트를 읽어 직접 만든다.
# 그래서 여기서 막지 않는다 -- fixed_paths.tcl 을 돌린 그 세션에서 파이썬 없이
# 바로 이어갈 수 있게 하려는 것이다.
if {![get_app_var si_enable_analysis]} {
    puts "  WARNING: si_enable_analysis is OFF. all crosstalk values will be 0."
}


# --- 잔일 (안 봐도 된다) ----------------------------------------------
proc xt_clean {s} {
    return [string map {"\t" " " "\n" " " "\r" " "} $s]
}

proc xt_attr {obj name} {
    set v ""
    if {[catch {set v [get_attribute -quiet $obj $name]}]} { return "" }
    return $v
}

proc xt_pick {vals want} {
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

# report_delay_calculation 출력에서 aggressor 넷 이름을 긁는다.
#   "   Aggressor   Coupling   Driver ..." 헤더가 나오고
#   "  ------  ------  ------" 구분선 다음부터 표 본문이다.
#   본문 줄의 첫 토큰이 넷 이름. 빈 줄이나 새 헤더가 나오면 끝.
# 넉넉히 긁혀도 무해하므로(사전 조회용) 엄격하게 걸러내지 않는다.
proc xt_scrape_aggressors {text} {
    set out {}
    set state 0
    foreach line [split $text "\n"] {
        if {[string first "Aggressor" $line] >= 0 \
            && [string first "Coupling" $line] >= 0} { set state 1 ; continue }
        if {$state == 1} {
            if {[regexp {^\s*-{3,}} $line]} { set state 2 }
            continue
        }
        if {$state == 2} {
            if {[string trim $line] eq ""} { set state 0 ; continue }
            # 넷 이름 줄은 **정확히 두 칸** 들여쓰기로 시작한다.
            #   "  ZCTSNET_6903        0.000240    gt3_6t_inv_x12_rvt"
            # 이름이 길면 줄바꿈되어 이름만 홀로 있기도 하다.
            #   "  FpPipeline_fp_issue_unit/n3547"
            # 그 아래 이어지는 값 줄은 훨씬 깊게 들여써 있으므로 걸러진다.
            if {![regexp {^  (\S+)} $line -> nm]} continue
            if {[string index $nm 0] eq "-"} continue
            dict set out $nm 1
        }
    }
    if {[info exists out]} { return [dict keys $out] }
    return {}
}


# 리포트에서 (넷, driver핀, load핀) 을 직접 뽑는다.
#   기본 : 넷 줄 바로 앞 핀 = driver, 바로 뒤 핀 = load
#   예외 : 앞이 핀이 아니면(포트/클럭 입구) 뒤의 두 핀을 driver/load 로
# 파이썬 5a 와 같은 결과가 나오는 것을 확인했다(788/788 일치).
# 이 덕에 fixed_paths.tcl 을 돌린 그 세션에서 파이썬 없이 바로 이어갈 수 있다.
proc xt_build_contexts {rpt} {
    set out {}
    set fh [open $rpt r]
    set prev_pin ""
    set pend {}
    while {[gets $fh line] >= 0} {
        if {![regexp {^  (\S+) \(([^)]+)\)} $line -> nm tag]} continue
        if {$tag eq "net"} {
            lappend pend [list $nm $prev_pin]
            continue
        }
        if {[string first "/" $nm] < 0} { set prev_pin "" ; continue }
        set newpend {}
        foreach e $pend {
            set net [lindex $e 0]
            set drv [lindex $e 1]
            if {$drv eq ""} {
                set drv $nm
                lappend newpend [list $net $drv]
                continue
            }
            dict set out "$net\t$drv\t$nm" 1
        }
        set pend $newpend
        set prev_pin $nm
    }
    close $fh
    return [dict keys $out]
}


# --- 넷 목록이 없으면 리포트에서 직접 만든다 --------------------------
if {![file exists $CTX]} {
    set RPT ""

    # (0) 맨 위에서 직접 박았으면 그것. 제일 우선한다.
    if {$RPT_FILE ne ""} {
        if {![file exists $RPT_FILE]} {
            puts "=================================================================="
            puts "  PROBLEM"
            puts "    what   : the report set in RPT_FILE does not exist."
            puts "             $RPT_FILE"
            puts "    action : fix the path on the RPT_FILE line at the top."
            puts ""
            puts "    code   : E-NORPTFILE"
            puts "=================================================================="
            return
        }
        set RPT $RPT_FILE
        puts "  using report from RPT_FILE : $RPT"
    }

    # (1) 같은 세션에서 fixed_paths.tcl 을 방금 돌렸으면 그 파일을 그대로 쓴다.
    #     OUT 은 fixed_paths.tcl 이 "$CORNER.rpt" 로 잡아 둔 것이다. 이게 제일
    #     확실하다 -- 폴더를 뒤질 필요가 없다.
    #     코너를 바꿔 cd 했는데 fixed_paths 를 안 돌렸다면 그 이름의 파일이
    #     없으므로 아래 에러로 간다(앞 코너 값을 잘못 쓰지 않는다).
    if {$RPT eq "" && [info exists OUT] && [file exists $OUT]} {
        set RPT $OUT
        puts "  using report just made by fixed_paths.tcl : $RPT"
    }

    # 확실하지 않으면 추측하지 않고 멈춘다.
    # 예전에는 폴더의 .rpt 를 훑어 첫 번째를 조용히 집었는데, 1회차 리포트나
    # 다른 코너 리포트를 잡으면 넷이 전부 PIN_NOT_FOUND 로 나면서
    # (E-XCALC0) 원인을 찾기 어려웠다.
    if {$RPT eq ""} {
        puts "=================================================================="
        puts "  PROBLEM"
        puts "    what   : no report was selected to read."
        puts "    action : do one of the two."
        puts "             (1) set RPT_FILE at the top of this file"
        puts "                   set RPT_FILE \"/data/round2/<corner>/<corner>.rpt\""
        puts "             (2) run fixed_paths.tcl first in the same session"
        puts "                   (its output is then picked up automatically)"
        puts ""
        puts "    code   : E-NORPTFILE"
        puts "=================================================================="
        return
    }
    puts "  no net list found -- building it from the report : $RPT"
    file mkdir $XTALK_DIR
    set rows [xt_build_contexts $RPT]
    set f [open $CTX w]
    puts $f "context_id\tvictim_net\tvictim_driver_pin\tvictim_load_pin\tfirst_path_id\tfirst_arc_idx\toccurrence_count"
    set i 0
    foreach r $rows { incr i ; puts $f "$i\t$r\t\t\t" }
    close $f
    puts "  net list built : [llength $rows] rows  ->  $CTX"
}

puts "--------------------------------------------------------------------"
puts "  directory : [pwd]"
puts "  analysis  : [expr {$DELAY_TYPE eq {min} ? {hold (-min)} : {setup (-max)}}]"
puts "  SI        : [expr {[get_app_var si_enable_analysis] ? {ON} : {OFF  <- all crosstalk will be 0}}]"
puts "--------------------------------------------------------------------"
puts "  reading net list : $CTX"

set cf [open $CTX r]
gets $cf header
set rf [open $RAW w]

set total 0
set ok 0
set err 0
set victim_pins {}
set aggr_nets {}

while {[gets $cf line] >= 0} {
    if {[string trim $line] eq ""} continue
    incr total

    set fields [split $line "\t"]
    set cid    [lindex $fields 0]
    set victim [lindex $fields 1]
    set driver [lindex $fields 2]
    set load   [lindex $fields 3]

    dict set victim_pins $load 1

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

    if {$status eq "OK"} {
        incr ok
        # 방금 받은 출력에서 aggressor 이름을 바로 긁는다 -> 파이썬 왕복이 없어진다
        foreach a [xt_scrape_aggressors $text] { dict set aggr_nets $a 1 }
    } else {
        incr err
    }

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
puts "  nets queried    : $total  (ok $ok / fail $err)"
puts "  aggressors seen : [dict size $aggr_nets]"

if {$ok == 0} {
    puts ""
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : not a single net could be calculated."
    puts "    action : open $RAW and read the 'message=' lines."
    puts ""
    puts "    code   : E-XCALC0"
    puts "=================================================================="
    return
}


# --- 이어서 도착시각/slew (원래 PT 2차) -------------------------------
puts ""
puts "  collecting arrival / slew ..."

set out [open $VOUT w]
puts $out "victim_load_pin\tvictim_load_min_arrival\tvictim_load_max_arrival\tmin_rise\tmax_rise\tmin_fall\tmax_fall\tslew_max\tstatus"
set nv 0
set nv_bad 0
foreach p [dict keys $victim_pins] {
    incr nv
    set row [xt_window $p]
    if {[lindex $row end] ne "OK"} { incr nv_bad }
    puts $out [join $row "\t"]
}
close $out
puts "  victim pins    : $nv  (not found $nv_bad)"

set out [open $AOUT w]
puts $out "aggressor_net\taggressor_driver_pin\taggressor_driver_min_arrival\taggressor_driver_max_arrival\tmin_rise\tmax_rise\tmin_fall\tmax_fall\taggressor_driver_slew_max\tstatus"
set na 0
set na_bad 0
foreach n [dict keys $aggr_nets] {
    incr na
    set drv [xt_driver $n]
    if {$drv eq ""} {
        incr na_bad
        puts $out "[xt_clean $n]\t\t\t\t\t\t\t\t\tNO_DRIVER"
        continue
    }
    set row [xt_window $drv]
    puts $out "[xt_clean $n]\t[join $row "\t"]"
}
close $out
puts "  aggressor nets : $na  (no driver $na_bad)"


# --- 자가 점검 : 값이 실제로 들어왔는지 --------------------------------
# 파일이 만들어졌다고 끝이 아니다. crosstalk 이 전부 0 이면 SI 설정 문제이고,
# 그대로 넘어가면 나중에 학습 데이터가 통째로 무의미해진다.
set n_bump 0
set fh [open $RAW r]
while {[gets $fh l] >= 0} {
    if {[regexp {Switching Bump} $l]} continue
    if {[regexp {^\s+\S+\s+[0-9.]+\s+\S+} $l] && [regexp {[0-9]\.[0-9]} $l]} { incr n_bump }
}
close $fh

puts ""
puts "===================================================================="
puts "  RESULT"
puts "--------------------------------------------------------------------"
puts [format "  %-16s %s" "nets queried"   "$total  (ok $ok / fail $err)"]
puts [format "  %-16s %s" "aggressor nets" "[dict size $aggr_nets]  (no driver $na_bad)"]
puts [format "  %-16s %s" "victim pins"    "$nv  (not found $nv_bad)"]
puts [format "  %-16s %s" "raw PT output"  "$RAW  ([file size $RAW] bytes)"]
puts "--------------------------------------------------------------------"

set bad 0
if {$err > 0} {
    puts "  CHECK   : $err nets failed."
    puts "            grep 'status=ERROR' in $RAW and read message=."
    puts "            many PIN_NOT_FOUND means this corner's netlist"
    puts "            does not match the report."
    puts "            code: W-XCALCERR"
    set bad 1
}
if {[dict size $aggr_nets] == 0} {
    puts "  PROBLEM : no aggressor found at all."
    puts "            SI is off, or the SPEF has no coupling caps."
    puts "            check with: printvar si_enable_analysis"
    puts "            read_parasitics needs -keep_capacitive_coupling."
    puts "            code: E-NOAGGR"
    set bad 1
}
if {$na_bad > [expr {[dict size $aggr_nets] / 2}]} {
    puts "  CHECK   : more than half of the aggressors have no driver."
    puts "            naming convention may differ.  code: W-NODRIVER"
    set bad 1
}
if {$bad == 0} {
    puts "  finished normally   \[ OK-XTALK \]"
}
puts "===================================================================="
puts ""
puts "next, in the shell (PrimeTime is no longer needed):"
puts "    python3 5a_contexts.py --dir [pwd]"
puts "    python3 5b_pairs.py    --dir [pwd]"
puts "    python3 5c_report.py   --dir [pwd]"
