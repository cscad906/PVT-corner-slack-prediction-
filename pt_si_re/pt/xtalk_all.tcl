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
# **이 파일은 setup(-max) 판이다.** hold 는 xtalk_all_hold.tcl 을 쓴다.
# 둘은 DELAY_TYPE 한 줄만 다르고, 결과 폴더도 <db이름>/xtalk 과
# <db이름>_hold/xtalk 으로 갈려 같은 자리에서 돌려도 안 섞인다.
#
# 화면 출력은 전부 영어(ASCII)다. pt_shell 이 한글을 깨뜨리는 환경이 있어서
# 일부러 그렇게 했다. 이 주석들은 화면에 안 나오므로 한글 그대로 둔다.
# =====================================================================


# =====================================================================
# 화면에 나오는 것을 **스스로 파일로 남긴다**
# =====================================================================
# 돌리는 사람과 데이터를 받는 사람이 다르고, 받는 쪽은 화면을 못 본다.
# 그렇다고 "-output_log_file 로 돌려 주세요" 같은 부탁을 매번 드릴 수도 없다.
# 그래서 이 파일이 자기 출력을 알아서 남긴다. 돌리는 방법은 그대로다.
#
#     pt_shell> source .../pt/xtalk_all.tcl
#     ->  <현재폴더>/xtalk_all_run.log  에 화면 내용이 그대로 남는다
#
# 방법: 자기 자신을 redirect -tee 안에서 한 번 더 source 한다. 두 번째
# 진입에서는 XT_LOGGING 이 이미 있으므로 이 블록을 건너뛰고 본문을 실행한다.
# -tee 라 화면에도 그대로 나온다. Tcl 에러가 나도 잡아서 로그에 적는다.
if {![info exists XT_LOGGING]} {
    set XT_LOGGING 1
    set XT_LOGFILE "[pwd]/xtalk_all_run.log"
    set XT_SELF [info script]
    set XT_RC [catch {
        redirect -tee -file $XT_LOGFILE { source $XT_SELF }
    } XT_ERR]
    if {$XT_RC} {
        # 에러 본문(while executing 포함)을 로그 끝에 붙인다.
        if {![catch {set _lf [open $XT_LOGFILE a]}]} {
            puts $_lf ""
            puts $_lf "=================================================================="
            puts $_lf "  TCL ERROR"
            puts $_lf $XT_ERR
            if {[info exists ::errorInfo]} {
                puts $_lf ""
                puts $_lf $::errorInfo
            }
            puts $_lf "=================================================================="
            close $_lf
        }
        puts "  (the error above is also in $XT_LOGFILE)"
    }
    puts ""
    puts "  screen log saved : $XT_LOGFILE"
    unset XT_LOGGING
    return
}

### 여기 세 줄만 고치면 된다 ###########################################
set RPT_FILE   ""         ;# 읽을 리포트. **절대경로로 박아도 된다.**
                           # 비워 두면 자동으로 찾는다(아래 순서).
set XTALK_DIR  ""         ;# 결과를 쓸 폴더. 비워 두면 **로드된 db 이름**으로
                           # 코너별 폴더를 만든다:  <db이름>/xtalk/
                           # db 를 못 알아내면 그냥 xtalk/ 에 쓴다.
set DELAY_TYPE "max"      ;# setup=max, hold=min
#######################################################################
if {[info exists XT_DELAY]} { set DELAY_TYPE $XT_DELAY }  ;# 루프가 준 값이 있으면 그것
# XT_RPT / XT_DIR 은 **쓰고 바로 지운다(일회용)**.
# 세션에 남겨 두면 다음 디자인·다음 코너까지 따라온다. 실제로 PERI 를 돌린
# 세션에서 MFC 를 돌렸더니 PERI 리포트가 그대로 읽힌 일이 있었다.
if {[info exists XT_RPT]}   { set RPT_FILE   $XT_RPT ; unset XT_RPT }
if {[info exists XT_DIR]}   { set XTALK_DIR  $XT_DIR ; unset XT_DIR }
                                                          #   set XT_RPT "/data/.../<코너>.rpt"
                                                          #   source .../xtalk_all.tcl

# 디자인 대조를 일부러 건너뛰고 싶을 때만 쓴다. 이것도 일회용이다.
set XT_SKIPDES 0
if {[info exists XT_SKIP_DESIGN_CHECK]} {
    set XT_SKIPDES $XT_SKIP_DESIGN_CHECK
    unset XT_SKIP_DESIGN_CHECK
}

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

# fixed_paths.tcl 이 같은 세션에 DTYPE 을 남긴다(max=setup, min=hold).
# 그것과 이 파일의 DELAY_TYPE 이 다르면 setup 경로를 hold 로 재는 식이 된다.
# 값을 몰래 바꾸지는 않는다 -- 어느 쪽이 맞는지는 사람이 안다. 알려만 준다.
if {[info exists DTYPE] && $DTYPE ne $DELAY_TYPE} {
    puts ""
    puts "  WARNING: fixed_paths.tcl in this session used -delay_type $DTYPE,"
    puts "           but this file is set to $DELAY_TYPE."
    puts "           setup and hold are two separate data sets -- mixing them"
    puts "           gives numbers that look fine but are meaningless."
    puts "           use xtalk_all.tcl for setup (max), xtalk_all_hold.tcl for hold (min)."
    puts ""
}


# --- 결과를 코너별 폴더에 쓴다 ----------------------------------------
# 한 폴더에서 코너를 여러 개 돌려도 서로 안 덮어쓰게 해야 한다.
# PT 가 코너를 알려주는 통로는 link_path 뿐이다 -- lib 이름은 op_cond_all 처럼
# 코너와 무관하고 nom_voltage/file_name 은 비어 있다(실측 확인).
#   link_path : * /.../db/TT_0p6V_25C_op_cond_all.db   ->  TT_0p6V_25C_op_cond_all
# 이 이름으로 폴더를 만들면 파이썬이 그대로 --dir 로 받는다.
set XT_DBSTEM ""
if {![catch {set XT_LP [get_app_var link_path]}]} {
    foreach e $XT_LP {
        if {[string match "*.db" $e] || [string match "*.lib" $e]} {
            set XT_DBSTEM [file rootname [file tail $e]]
        }
    }
}
if {$XTALK_DIR eq ""} {
    if {$XT_DBSTEM ne ""} {
        # setup 과 hold 는 완전히 별개 2세트다. 같은 자리에서 연달아 돌려도
        # 안 덮어쓰게 hold 는 폴더 이름에 _hold 를 붙인다.
        if {$DELAY_TYPE eq "min"} {
            set XTALK_DIR "${XT_DBSTEM}_hold/xtalk"
        } else {
            set XTALK_DIR "$XT_DBSTEM/xtalk"
        }
    } else {
        set XTALK_DIR "xtalk"
        puts "  NOTE: could not tell which db is loaded (link_path has no .db/.lib),"
        puts "        so results go to ./xtalk .  if you run more than one corner"
        puts "        in this directory they would overwrite each other -- give"
        puts "        each corner its own directory, or set XTALK_DIR at the top."
    }
}

set CTX  "$XTALK_DIR/unique_contexts.tsv"
set RAW  "$XTALK_DIR/context_raw.rpt"
set VOUT "$XTALK_DIR/victim_windows.tsv"
set AOUT "$XTALK_DIR/aggressor_windows.tsv"


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
#
# 지나가는 김에 경로 개수도 센다(어차피 파일을 한 번 다 읽으므로 공짜다).
#   XT_NPATH  "### FIXED_PATH" 줄 수      = 리포트에 담긴 경로 수
#   XT_NSLACK "slack (" 줄 수             = 끝까지 온전히 적힌 경로 수
# 리포트가 도중에 잘리면 마지막 블록에 slack 줄이 없어 둘이 어긋난다.
# 리포트 머리말의 "Design : <이름>" 을 읽는다. 못 찾으면 "" 를 준다.
# report_timing 이 경로마다 머리말을 다시 찍으므로 맨 앞에서 바로 나온다.
# 그래도 못 찾을 때를 대비해 200줄만 보고 그만둔다.
proc xt_report_design {rpt} {
    set d ""
    if {[catch {set fh [open $rpt r]}]} { return "" }
    set n 0
    while {[gets $fh line] >= 0} {
        incr n
        if {[regexp {^Design\s*:\s*(\S+)} $line -> d]} { break }
        if {$n > 200} { set d "" ; break }
    }
    close $fh
    return $d
}

# 이번 실행이 어떤 조건에서 돌았는지 파일로 남긴다.
#
# 왜 파일인가
#     현장에서 돌리시는 분과 데이터를 받는 분이 다르다. 받는 쪽은 **화면을
#     못 본다.** 그래서 "어느 디자인·어느 db·어느 리포트로 돌았나" 가 화면에만
#     있으면 전달되지 않는다. 결과와 같은 폴더에 파일로 남겨야 같이 돌아온다.
#
#     폴더 이름은 link_path 의 db 에서 따오는데 db 가 여러 개면 헷갈릴 수 있다
#     (macro 를 다른 전압 db 로 물리는 경우). 이 파일이 있으면 폴더 이름이
#     무엇이든 조건이 확정된다.
proc xt_write_run_info {path rows} {
    if {[catch {set f [open $path w]}]} { return }
    foreach {k v} $rows {
        puts $f [format "%-14s %s" $k $v]
    }
    close $f
}


# 지금 PT 에 물려 있는 디자인 이름. 못 읽으면 "".
proc xt_current_design {} {
    if {[catch {set d [get_object_name [current_design]]}]} { return "" }
    return $d
}


proc xt_build_contexts {rpt} {
    global XT_NPATH XT_NSLACK
    set XT_NPATH 0
    set XT_NSLACK 0
    set out {}
    set fh [open $rpt r]
    set prev_pin ""
    set pend {}
    while {[gets $fh line] >= 0} {
        # 세는 것부터. 아래 regexp 에 안 걸리는 줄들이라 여기서 처리한다.
        # 후보 검사와 같은 규칙으로 본다. 한쪽만 BOM 을 걷어내면, 통과는
        # 했는데 경로를 0개로 읽는 어긋난 상태가 된다.
        if {[string match "### FIXED_PATH*" [string trimleft $line "\uFEFF \t\r"]]} {
            incr XT_NPATH ; continue
        }
        if {[string match "  slack (*" $line]}      { incr XT_NSLACK }
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
# 이미 있으면 리포트를 안 읽으므로 RPT 는 빈 채로 남는다(맨 아래 안내에서 씀).
set RPT ""
# --- 넷 목록을 리포트에서 만든다 (매번 새로) --------------------------
# 예전에는 "unique_contexts.tsv 가 이미 있으면 안 만들고 그대로 쓴다" 였다.
# 그게 사고의 원인이었다. 앞 디자인 목록이 폴더에 남아 있으면 리포트를 아예
# 안 읽고 그것을 써서, 넷이 하나도 안 맞아 E-XCALC0 로 끝난다. 게다가 디자인
# 대조가 이 블록 안에 있어서 검사까지 같이 건너뛰었다.
#
# 그래서 **항상 다시 만든다.** 옆의 context_raw / victim_windows /
# aggressor_windows 는 원래도 매번 덮어썼다. 목록만 재활용되던 것이 오히려
# 어긋난 규칙이었고, 이제 네 파일이 늘 같은 기준이 된다.
# 비용은 리포트를 한 번 흘려 읽는 것뿐이다.

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

# (1) 예전에는 여기서 fixed_paths.tcl 이 남긴 $OUT 을 그대로 썼다. 없앴다.
#     이유 두 가지.
#       - 세션 변수라 아무도 안 지운다. 앞 디자인/앞 코너 값이 그대로 남아
#         다음 번에 딸려 온다(PERI 를 돌린 세션에서 MFC 를 돌린 사고).
#       - 없어도 잃는 것이 없다. $OUT 은 "$CORNER.rpt" 라는 **상대 이름**이라
#         리포트가 현재 폴더에 떨어지는데, 아래 (2) 폴더 스캔도 현재 폴더를
#         본다. (1) 이 찾던 파일은 (2) 도 반드시 찾는다.

# (2) 이 폴더에서 fixed_paths.tcl 산출물을 **내용으로** 찾는다.
#     이름으로 찾지 않는다 -- 폴더 이름과 리포트 이름이 다를 수 있고,
#     pt_shell 을 새로 띄웠으면 위 OUT 도 없기 때문이다.
#
#     구분 기준 : fixed_paths.tcl 이 만든 리포트는 **첫 줄이
#     "### FIXED_PATH" 로 시작**한다. 1회차 report_timing 리포트에는
#     이 표시가 없으므로 절대 잘못 집히지 않는다.
#     우리 최종 산출물(*by_path.rpt)도 같은 표시로 시작하므로 이름으로 뺀다.
#
#     후보가 둘 이상이면 고르지 않고 멈춘다(엉뚱한 코너를 집으면
#     넷이 전부 PIN_NOT_FOUND 로 나면서 원인을 찾기 어려워진다).
set XT_CAND {}
set XT_WHY {}
if {$RPT eq ""} {
    foreach f [lsort [glob -nocomplain -directory [pwd] -tails *.rpt]] {
        if {[string match "*by_path.rpt" $f]} {
            lappend XT_WHY [list $f "skipped -- this is our own output"]
            continue
        }
        # **왜 탈락했는지 남긴다.** 예전에는 조용히 건너뛰어서, 파일은 목록에
        # 보이는데 후보에서 빠지고 이유를 알 길이 없었다. 특히 권한 등으로
        # open 이 실패하는 경우가 그랬다(로그만 보는 쪽에서는 손쓸 수가 없다).
        if {[catch {set fh [open $f r]} XT_OE]} {
            lappend XT_WHY [list $f "could not open -- $XT_OE"]
            continue
        }
        if {[catch {gets $fh first} XT_GE]} {
            catch {close $fh}
            lappend XT_WHY [list $f "could not read -- $XT_GE"]
            continue
        }
        close $fh
        # BOM 과 앞 공백을 걷어낸다. 눈에는 안 보이는데 string match 는 실패한다.
        set XT_HEAD [string trimleft $first "\uFEFF \t\r"]
        if {[string match "### FIXED_PATH*" $XT_HEAD]} {
            lappend XT_CAND $f
        } else {
            lappend XT_WHY [list $f "first line is not '### FIXED_PATH' -- \"[string range $XT_HEAD 0 50]\""]
        }
    }
    # 후보가 여럿이어도 멈추지 않는다. **어느 코너의 리포트를 읽든 결과가
    # 같기 때문이다.** 여기서 리포트에서 뽑는 것은 경로와 넷 구조뿐이고,
    # 그건 고정 경로라 코너가 달라도 동일하다(4개 코너로 확인 -- 리포트
    # 파일은 slack 이 달라 서로 다르지만, 뽑힌 넷 목록은 byte 단위로 같았다).
    # crosstalk 숫자는 리포트가 아니라 지금 로드된 디자인에서 나온다.
    #
    # 그래도 지금 코너의 것을 우선 고른다 -- 화면에 찍히는 이름이
    # 로드된 db 와 맞아야 사람이 덜 헷갈린다.
    if {[llength $XT_CAND] > 1 && $XT_DBSTEM ne ""} {
        foreach f $XT_CAND {
            if {[string first [file rootname $f] $XT_DBSTEM] >= 0} {
                set XT_CAND [list $f]
                puts "  matched the loaded db : $XT_DBSTEM"
                break
            }
        }
    }
    if {[llength $XT_CAND] > 1} {
        puts "  [llength $XT_CAND] fixed-path reports are here; using the first."
        puts "  (any of them gives the same net list -- only the numbers"
        puts "   differ between corners, and those are not used here.)"
        foreach f $XT_CAND { puts "     $f" }
    }
    if {[llength $XT_CAND] >= 1} {
        set RPT [lindex $XT_CAND 0]
        puts "  found the fixed-path report : $RPT"
    }
}

# 그래도 없으면 멈춘다. 추측하지 않는다.
if {$RPT eq ""} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : no fixed-path report was found."
    puts "             looked in : [pwd]"
    puts "             a fixed-path report is a .rpt file whose first line"
    puts "             starts with '### FIXED_PATH' (made by fixed_paths.tcl)."
    set XT_ANY [glob -nocomplain -directory [pwd] -tails *.rpt]
    if {[llength $XT_ANY] == 0} {
        puts "             there is no .rpt file here at all."
        puts "    action : cd to the corner directory that holds the report,"
        puts "             then source this file again."
    } else {
        puts "             .rpt files that are here, and why each was rejected:"
        if {[info exists XT_WHY] && [llength $XT_WHY]} {
            foreach e $XT_WHY {
                puts "               [lindex $e 0]"
                puts "                   [lindex $e 1]"
            }
        } else {
            foreach f $XT_ANY { puts "               $f" }
        }
        puts "    action : if one of the above IS the fixed-path report,"
        puts "             name it at the top of this file:"
        puts "               set RPT_FILE \"<name>\""
        puts "             a round-1 report will not work -- it has no"
        puts "             '### FIXED_PATH' lines, so paths cannot be matched."
    }
    puts ""
    puts "    code   : E-NORPTFILE"
    puts "=================================================================="
    return
}
# --- 이 리포트가 **이 디자인** 것인가 -----------------------------
# 리포트에는 "Design : <이름>" 이 박혀 있고 PT 에는 current_design 이 있다.
# 둘이 다르면 넷 이름이 하나도 안 맞아 전부 PIN_NOT_FOUND 로 끝나는데,
# 그 사이 몇 시간이 그냥 간다. 그러니 한 줄도 계산하기 전에 멈춘다.
set XT_RDES [xt_report_design $RPT]
set XT_CDES [xt_current_design]

# --- 이번 실행 조건을 파일로 남긴다 -----------------------------------
# **판정보다 먼저 쓴다.** 어긋나서 멈추는 경우야말로 증거가 필요한데, 화면은
# 받는 쪽에 전달되지 않기 때문이다(돌리는 사람과 데이터를 받는 사람이 다르다).
set XT_NDB 0
set XT_DBLIST {}
if {[info exists XT_LP]} {
    foreach e $XT_LP {
        if {[string match "*.db" $e] || [string match "*.lib" $e]} {
            incr XT_NDB
            lappend XT_DBLIST $e
        }
    }
}
if {$XT_SKIPDES} {
    set XT_DVERD "skipped (XT_SKIP_DESIGN_CHECK)"
} elseif {$XT_RDES eq "" || $XT_CDES eq ""} {
    set XT_DVERD "unknown (no name to compare)"
} elseif {$XT_RDES eq $XT_CDES} {
    set XT_DVERD "ok"
} else {
    set XT_DVERD "MISMATCH"
}
file mkdir $XTALK_DIR
set XT_INFO "$XTALK_DIR/run_info.txt"
set XT_ROWS [list \
    date             [clock format [clock seconds] -format "%Y-%m-%d %H:%M:%S"] \
    current_design   [expr {$XT_CDES eq "" ? "?" : $XT_CDES}] \
    report_file      [file normalize $RPT] \
    report_design    [expr {$XT_RDES eq "" ? "?" : $XT_RDES}] \
    design_check     $XT_DVERD \
    delay_type       $DELAY_TYPE \
    analysis         [expr {$DELAY_TYPE eq "min" ? "hold" : "setup"}] \
    directory        [pwd] \
    xtalk_dir        [file normalize $XTALK_DIR] \
    db_used_for_name [expr {$XT_DBSTEM eq "" ? "?" : $XT_DBSTEM}] \
    n_db             $XT_NDB \
    si_enabled       [expr {[get_app_var si_enable_analysis] ? "yes" : "no"}]]
foreach e $XT_DBLIST { lappend XT_ROWS db $e }
xt_write_run_info $XT_INFO $XT_ROWS
puts "  run info    : $XT_INFO"
if {$XT_NDB > 1} {
    puts "  NOTE: $XT_NDB libraries are linked.  the folder name comes from one of"
    puts "        them, so read run_info.txt (not the folder name) to know what"
    puts "        this run actually used."
}

if {!$XT_SKIPDES && $XT_RDES ne "" && $XT_CDES ne "" && $XT_RDES ne $XT_CDES} {
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : that report was made from a different design."
    puts "             report says   : $XT_RDES"
    puts "             loaded design : $XT_CDES"
    puts "             report file   : $RPT"
    puts "             directory     : [pwd]"
    puts "    action : cd to THIS design's corner directory and source again,"
    puts "             or name the right report at the top of this file:"
    puts "               set RPT_FILE \"<path to $XT_CDES report>\""
    puts "             if the two names really are the same design, run"
    puts "               set XT_SKIP_DESIGN_CHECK 1"
    puts "             and source again (that switch clears itself)."
    puts ""
    puts "    code   : E-DESIGNMISMATCH"
    puts "=================================================================="
    return
}
if {$XT_SKIPDES} {
    puts "  NOTE: design check skipped on request (XT_SKIP_DESIGN_CHECK)."
} elseif {$XT_RDES eq ""} {
    puts "  NOTE: the report has no 'Design :' line, so it could not be"
    puts "        checked against the loaded design."
} elseif {$XT_CDES eq ""} {
    puts "  NOTE: current_design could not be read, so the report was not"
    puts "        checked against it."
} else {
    puts "  design      : $XT_CDES   <- report agrees"
}

# 로드된 db 를 같이 찍어 둔다. 리포트 이름과 달라도 문제가 아니다
# (넷 목록은 코너와 무관하다). 나중에 로그만 보고도 어느 db 로 계산했는지
# 알 수 있게 남기는 것이다.
if {$XT_DBSTEM ne ""} {
    puts "  loaded db   : $XT_DBSTEM   <- crosstalk is computed with this db"
}
puts "  building the net list from the report : $RPT   (always rebuilt)"
file mkdir $XTALK_DIR
set rows [xt_build_contexts $RPT]
set f [open $CTX w]
puts $f "context_id\tvictim_net\tvictim_driver_pin\tvictim_load_pin\tfirst_path_id\tfirst_arc_idx\toccurrence_count"
set i 0
foreach r $rows { incr i ; puts $f "$i\t$r\t\t\t" }
close $f
puts "  paths in report : $XT_NPATH"
puts "  net list built  : [llength $rows] rows  ->  $CTX"

# 리포트가 도중에 잘렸는지 본다. 잘린 채로 넘어가면 그 뒤 경로의 넷이
# 통째로 빠지는데, 남은 것만으로도 계산은 멀쩡히 돌아 OK 로 끝난다.
# 그래서 여기서 잡지 않으면 학습 데이터가 조용히 반쪽이 된다.
if {$XT_NPATH == 0} {
    puts ""
    puts "  WARNING: this report has no '### FIXED_PATH' line at all."
    puts "           it may not be a fixed_paths.tcl output."
    puts "           code: W-NOPATHS"
    puts ""
} elseif {$XT_NSLACK < $XT_NPATH} {
    puts ""
    puts "  WARNING: the report looks cut short."
    puts "             paths started  : $XT_NPATH"
    puts "             paths finished : $XT_NSLACK   <- fewer"
    puts "           the last [expr {$XT_NPATH - $XT_NSLACK}] path(s) have no 'slack' line,"
    puts "           so their nets are missing from the list above."
    puts "           this run will still finish and print OK, but the data"
    puts "           will be incomplete."
    puts "           re-run fixed_paths.tcl and check it reached the end"
    puts "           (it prints 'requested / measured' when it finishes)."
    puts "           code: W-RPTCUT"
    puts ""
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

# 실행 결과를 run_info.txt 에 덧붙인다.
# **이 줄들이 없으면 도중에 멈춘 것이다.** 받는 쪽은 화면을 못 보므로,
# 파일에 result 가 있는지로 완주 여부를 판단한다.
if {[info exists XT_INFO] && ![catch {set f [open $XT_INFO a]}]} {
    puts $f [format "%-16s %s" nets_queried $total]
    puts $f [format "%-16s %s" nets_ok      $ok]
    puts $f [format "%-16s %s" nets_failed  $err]
    puts $f [format "%-16s %s" aggressors   [dict size $aggr_nets]]
    puts $f [format "%-16s %s" victim_pins  [dict size $victim_pins]]
    puts $f [format "%-16s %s" result       [expr {$ok > 0 ? "finished" : "E-XCALC0"}]]
    close $f
}

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
# 파이썬은 <dir>/xtalk/ 를 본다. 우리가 <db이름>/xtalk/ 에 썼으므로
# --dir 은 그 한 단계 위, 즉 xtalk 의 부모를 준다.
set XT_PYDIR [file normalize [file dirname $XTALK_DIR]]
puts "results are in : [file normalize $XTALK_DIR]"
puts ""
puts "next, in the shell (PrimeTime is no longer needed):"
if {$RPT ne ""} {
    puts "    python3 5a_contexts.py --dir $XT_PYDIR --annotated [file normalize $RPT]"
} else {
    puts "    python3 5a_contexts.py --dir $XT_PYDIR --annotated <the fixed-path report>"
}
puts "    python3 5b_pairs.py    --dir $XT_PYDIR"
puts "    python3 5c_report.py   --dir $XT_PYDIR"
