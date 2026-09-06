# PrimeTime scaling 입력 선택 확인 전용
# Tcl 또는 PrimeTime에서 아래 한 줄로 실행합니다. STA는 실행하지 않습니다.
#   source /home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/pt/check_scaling.tcl
#
# 아래 USER SETTINGS의 따옴표 안 값과 숫자만 바꾸면 됩니다.

# ======================= USER SETTINGS ========================

# 목표 코너와 보간 방향
set TARGET_PROCESS     "TT"       ;# TT / SS / FF
set TARGET_VOLTAGE    0.75        ;# Volt
set TARGET_TEMPERATURE 25         ;# Celsius. 영하 40도는 -40
set SCALING_AXIS       "V"        ;# V / T / VT
set RC_CORNER          ""         ;# 3nm 예제는 빈칸. 14nm은 Cmin/Cnom/Cmax

# 분석 종류
set ANALYSIS           "setup"    ;# setup / hold
set SI_ANALYSIS        "off"      ;# off / on
set CLOCK_SETTING      "propagated" ;# propagated / sdc

# 라이브러리 폴더. 같은 이름의 DB와 Lib가 있으면 DB를 사용합니다.
set DB_FOLDER  "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_benchmarks/deliverables/3nm/processors/BoomCoreV3/deliver/lib_db_pdk/db"
set LIB_FOLDER "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_benchmarks/deliverables/3nm/processors/BoomCoreV3/deliver/lib_db_pdk/lib"

# 디자인 입력
set TOP_MODULE   "BoomCore"
set NETLIST_FILE "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_benchmarks/deliverables/3nm/processors/BoomCoreV3/deliver/spef/boomcorev3_icc2.v"
set SDC_FILE     "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_benchmarks/deliverables/3nm/processors/BoomCoreV3/deliver/spef/boomcorev3.sdc"

# SPEF 파일 이름 규칙
# 3nm:  boomcorev3_25.spef, boomcorev3_70.spef, boomcorev3_m40.spef
# 14nm: boomcorev3_14nm.Cnom_model_25.spef 형태이며 RC_CORNER도 설정합니다.
set SPEF_FOLDER "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_benchmarks/deliverables/3nm/processors/BoomCoreV3/deliver/spef"
set SPEF_COMMON_NAME "boomcorev3"

# 반드시 pt_si_re/1_union.py가 만든 파일을 지정합니다.
set FIXED_PATH_FILE "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/example/round1/corners/fixed_paths.tcl"

# 결과 폴더. 파일명은 목표 코너와 설정으로 자동 생성하며 기존 파일은 덮어쓰지 않습니다.
set RESULT_FOLDER "/home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re/pt/auto_scaling_output"

# 단일 전원 설계의 전원 이름
set POWER_NET  "VDD"
set GROUND_NET "VSS"

# ===================== END USER SETTINGS =====================
# 아래 구현부는 수정하지 않아도 됩니다.
namespace eval auto_scaling {}

proc auto_scaling::need {cfg key} {
    if {![dict exists $cfg $key] || [dict get $cfg $key] eq ""} {
        error "Missing setting: $key"
    }
    return [dict get $cfg $key]
}
proc auto_scaling::option {cfg key fallback} {
    if {[dict exists $cfg $key]} { return [dict get $cfg $key] }
    return $fallback
}
proc auto_scaling::number {value} {
    set value [string map {p . m -} [string tolower $value]]
    if {![string is double -strict $value] || ![expr {abs(double($value)) < 1e100}]} {
        error "Invalid finite number: $value"
    }
    return [expr {double($value)}]
}
proc auto_scaling::same {a b} { return [expr {abs($a-$b) < 1e-8}] }
proc auto_scaling::readable {path} {
    if {![file isfile $path] || ![file readable $path]} { error "Cannot read file: $path" }
    return [file normalize $path]
}

# Exact target-temperature extraction only: never use a nearest-temperature SPEF.
# string map performs literal replacement, with no Tcl evaluation of the template.
proc auto_scaling::select_spef {cfg} {
    if {[dict exists $cfg spef]} {
        error "Replace the fixed spef setting with spef_template containing {temp}."
    }
    set template [need $cfg spef_template]
    if {[string first "{temp}" $template] < 0} {
        error "spef_template must contain {temp}; a fixed-temperature path is not allowed."
    }
    set temperature [number [need $cfg target_t]]
    set tag [format %.12g [expr {abs($temperature)}]]
    set tag [string map {. p} $tag]
    if {$temperature < 0} { set tag m$tag }
    set rc [option $cfg target_rc ""]
    if {[string first "{rc}" $template] >= 0 && $rc eq ""} {
        error "target_rc is required when spef_template contains {rc}."
    }
    if {$rc ne "" && [string first "{rc}" $template] < 0} {
        error "target_rc is set but spef_template has no {rc}; RC selection would be ignored."
    }
    set path [string map [list "{temp}" $tag "{rc}" $rc] $template]
    if {![file isfile $path] || ![file readable $path]} {
        error "No readable SPEF for target T=$temperature C, RC='$rc': $path. No temperature/RC substitution is performed."
    }
    return [file normalize $path]
}

# Read literal data from 1_union.py output WITHOUT sourcing its executable code.
# Legacy data-only files with "set FIXED_PATHS {...}" are also supported.
proc auto_scaling::read_fixed {path expected_type} {
    set path [readable $path]
    set fh [open $path r]
    fconfigure $fh -encoding utf-8
    set block ""
    set dtype ""
    set collecting 0
    set complete 0
    while {[gets $fh line] >= 0} {
        if {!$collecting} {
            if {[regexp {^\s*set\s+DTYPE\s+"?(max|min)"?(?:\s*;.*)?\s*$} $line -> value]} {
                set dtype $value
            }
            if {![regexp {^\s*set\s+FIXED_PATHS\s+\{} $line]} { continue }
            set collecting 1
            set block $line
            if {[info complete $block]} { set complete 1; break }
        } else {
            append block "\n" $line
            # Generated files close the literal list on its own line. Avoid
            # rescanning the entire list for every path in a large union.
            if {[string trim $line] eq "\}" && [info complete $block]} {
                set complete 1
                break
            }
        }
    }
    close $fh
    if {!$complete || [catch {llength $block} words] || $words != 3 ||
        [lindex $block 0] ne "set" || [lindex $block 1] ne "FIXED_PATHS"} {
        error "Expected a literal set FIXED_PATHS block in $path (1_union.py output). No Tcl commands were executed."
    }
    if {$dtype ne "" && $dtype ne $expected_type} {
        error "Fixed-path mode mismatch: file DTYPE=$dtype, scaling delay_type=$expected_type. Use the matching setup/hold union."
    }
    set paths [lindex $block 2]
    if {![llength $paths]} { error "FIXED_PATHS is empty: $path" }
    set seen [dict create]
    foreach item $paths {
        if {[llength $item] ni {4 5}} { error "Invalid fixed-path row (expected 4 or 5 fields): $item" }
        lassign $item key from to through edges
        if {$key eq "" || $from eq "" || $to eq ""} { error "Empty fixed-path key/from/to" }
        if {[dict exists $seen $key]} { error "Duplicate fixed-path key: $key" }
        dict set seen $key 1
        foreach pin $through { if {$pin eq ""} { error "Empty through pin: $key" } }
        if {[llength $edges]} {
            if {[llength $edges] != [llength $through]+2} { error "Invalid edge count: $key" }
            foreach edge $edges { if {$edge ni {r f}} { error "Invalid edge '$edge': $key" } }
        }
    }
    return [dict create file $path dtype $dtype count [llength $paths] paths $paths]
}

# File names encode the project's process labels; nominal process numbers alone
# cannot reliably distinguish SS/TT/FF. Overrides also support other naming schemes.
# override value: {process voltage temperature family}
proc auto_scaling::corner {path overrides} {
    if {[dict exists $overrides $path]} {
        set fields [dict get $overrides $path]
        if {[llength $fields] != 4} { error "corner_map entry needs {process voltage temperature family}: $path" }
        lassign $fields process v t family
    } else {
        set stem [file rootname [file tail $path]]
        set pattern {(tt|ss|ff|sf|fs)_?([0-9]+(?:[p.][0-9]+)?)v_?(m?[0-9]+(?:[p.][0-9]+)?|-[0-9]+(?:[p.][0-9]+)?)c}
        if {![regexp -nocase $pattern $stem token process v t]} {
            error "Cannot identify P/V/T: $path. Narrow library_globs or add a corner_map entry."
        }
        regsub -nocase $pattern $stem {PVT} family
        set family [string tolower $family]
    }
    return [dict create file $path process [string toupper $process] \
        v [number $v] t [number $t] family $family]
}

proc auto_scaling::catalog {cfg} {
    set files {}
    foreach pattern [need $cfg library_globs] {
        foreach path [glob -nocomplain -- $pattern] {
            if {[string tolower [file extension $path]] in {.lib .db}} {
                lappend files [readable $path]
            }
        }
    }
    set files [lsort -unique $files]
    if {![llength $files]} { error "No .lib/.db files matched library_globs" }
    # A same-stem .db is preferred over its .lib counterpart. Two different DBs
    # with the same stem are ambiguous; never silently select one revision.
    set stems [dict create]
    set shadows {}
    foreach path $files {
        set stem [file rootname [file tail $path]]
        set ext [string tolower [file extension $path]]
        if {[dict exists $stems $stem $ext]} {
            error "Duplicate $ext basename $stem: [dict get $stems $stem $ext] and $path. Narrow library_globs."
        }
        dict set stems $stem $ext $path
    }
    set rows {}
    set overrides [option $cfg corner_map {}]
    dict for {stem variants} $stems {
        if {[dict exists $variants .db]} {
            set path [dict get $variants .db]
            if {[dict exists $variants .lib]} { lappend shadows [dict get $variants .lib] }
        } else { set path [dict get $variants .lib] }
        lappend rows [corner $path $overrides]
    }
    return [dict create rows $rows shadows $shadows]
}

proc auto_scaling::bracket {values target axis} {
    set lower ""
    set upper ""
    foreach value [lsort -real -unique $values] {
        if {[same $value $target]} { continue }
        if {$value < $target} { set lower $value }
        if {$value > $target && $upper eq ""} { set upper $value }
    }
    if {$lower eq "" || $upper eq ""} {
        error "Cannot bracket target $axis=$target. Extrapolation is not enabled."
    }
    return [list $lower $upper]
}

# Pure Tcl: no PT commands, no library loads, no output files.
proc auto_scaling::plan {cfg} {
    set process [string toupper [need $cfg target_process]]
    set tv [number [need $cfg target_v]]
    set tt [number [need $cfg target_t]]
    set mode [string toupper [need $cfg mode]]
    if {$mode ni {V T VT}} { error "mode must be V, T, or VT (no automatic change of interpolation axis)" }
    set cat [catalog $cfg]
    set rows [dict get $cat rows]
    set families {}
    foreach row $rows {
        if {[dict get $row process] eq $process} { lappend families [dict get $row family] }
    }
    set families [lsort -unique $families]
    set family [option $cfg family ""]
    if {$family eq ""} {
        if {[llength $families] != 1} {
            error "Choose one library family using family or narrower globs. Candidates: $families"
        }
        set family [lindex $families 0]
    }
    set pool {}
    set excluded {}
    foreach row $rows {
        if {[dict get $row process] ne $process || [dict get $row family] ne $family} {
            continue
        } elseif {[same [dict get $row v] $tv] && [same [dict get $row t] $tt]} {
            # Exclude every exact target representation before building the group.
            lappend excluded $row
        } else { lappend pool $row }
    }
    set eligible {}
    set vs {}
    set ts {}
    foreach row $pool {
        set v [dict get $row v]
        set t [dict get $row t]
        if {$mode eq "V" && ![same $t $tt]} { continue }
        if {$mode eq "T" && ![same $v $tv]} { continue }
        lappend eligible $row
        lappend vs $v
        lappend ts $t
    }
    if {$mode eq "T"} { set vv [list $tv] } else { set vv [bracket $vs $tv voltage] }
    if {$mode eq "V"} { set tts [list $tt] } else { set tts [bracket $ts $tt temperature] }
    set selected {}
    foreach v $vv {
        foreach t $tts {
            set matches {}
            foreach row $eligible {
                if {[same [dict get $row v] $v] && [same [dict get $row t] $t]} { lappend matches $row }
            }
            if {[llength $matches] != 1} {
                error "Need exactly one library at $process/$v V/$t C; found [llength $matches]. Missing rectangle corner or duplicate revisions."
            }
            lappend selected [lindex $matches 0]
        }
    }
    set result [dict create process $process v $tv t $tt mode $mode family $family \
        selected $selected excluded $excluded catalog $rows shadows [dict get $cat shadows]]
    # Library-only callers may omit extraction settings. run always requires them.
    if {[dict exists $cfg spef_template] || [dict exists $cfg spef]} {
        dict set result spef [select_spef $cfg]
        dict set result rc [option $cfg target_rc ""]
    }
    if {[option $cfg fixed_tcl ""] ne ""} {
        dict set result fixed [read_fixed [dict get $cfg fixed_tcl] [option $cfg delay_type max]]
    }
    puts "TARGET: $process  $tv V  $tt C; mode=$mode; family=$family"
    foreach row $excluded { puts "EXCLUDED TARGET: [dict get $row file]" }
    if {![llength $excluded]} { puts "TARGET LIBRARY: absent (prediction only; no target library required)" }
    foreach row $selected { puts "SCALING INPUT: [dict get $row file]" }
    if {[dict exists $result spef]} { puts "TARGET SPEF: [dict get $result spef]" }
    if {[dict exists $result fixed]} {
        puts "FIXED PATHS: [dict get $result fixed count] from [dict get $result fixed file]"
    }
    puts "Same-stem LIB files superseded by DB: [llength [dict get $cat shadows]]"
    return $result
}

proc auto_scaling::check_status {label command} {
    set status [uplevel 1 $command]
    if {$status ne "1"} { error "$label failed (return=$status); do not use this run as a valid scaling result" }
}

# Run once per fresh PT session. This procedure returns after analysis and
# never calls exit/remove_design or sources the executable union report script.
proc auto_scaling::run {cfg} {
    need $cfg fixed_tcl
    set plan [plan $cfg]
    foreach command {get_designs get_libs define_scaling_lib_group} {
        if {![llength [info commands ::$command]]} { error "run requires pt_shell; plan can run in tclsh" }
    }
    if {[sizeof_collection [get_designs -quiet *]] || [sizeof_collection [get_libs -quiet *]]} {
        error "Use a fresh pt_shell with no loaded designs/libraries. Existing state is not deleted."
    }
    foreach key {top verilog sdc out_rpt spef_template} { need $cfg $key }
    foreach key {verilog sdc} { readable [dict get $cfg $key] }
    set spef [need $plan spef]
    set out [file normalize [dict get $cfg out_rpt]]
    foreach suffix {"" .selection.tcl .libgroups .dcalc} {
        if {[file exists ${out}${suffix}]} { error "Output already exists: ${out}${suffix}. Choose a new out_rpt." }
    }
    set dt [option $cfg delay_type max]
    if {$dt ni {max min}} { error "delay_type must be max or min" }
    set si [option $cfg si 0]
    if {$si ni {0 1}} { error "si must be 0 or 1" }
    set fixed [dict get $plan fixed]
    set clocks [need $cfg clock_mode]
    if {$clocks ni {sdc propagated}} { error "clock_mode must be sdc or propagated" }
    set rail [option $cfg rail_name VDD]
    set gnd [option $cfg ground_name VSS]
    if {$rail eq $gnd} { error "rail_name and ground_name must differ" }
    set dbs {}
    foreach row [dict get $plan selected] { lappend dbs [dict get $row file] }
    file mkdir [file dirname $out]
    set fp [open ${out}.selection.tcl w]
    puts $fp "# Selection only; target libraries were not loaded."
    set record $plan
    dict unset record fixed paths
    puts $fp [list set scaling_selection $record]
    close $fp
    # Use global scope for PT application variables and sourced SDC/path scripts.
    set_app_var si_enable_analysis $si
    set_app_var link_create_black_boxes false
    set ::link_path [linsert [list [lindex $dbs 0]] 0 *]
    define_scaling_lib_group $dbs
    check_status read_verilog [list read_verilog [dict get $cfg verilog]]
    current_design [dict get $cfg top]
    check_status link_design {link_design}
    check_status read_sdc [list read_sdc [dict get $cfg sdc]]
    if {$si} {
        check_status read_parasitics [list read_parasitics -keep_capacitive_coupling $spef]
    } else { check_status read_parasitics [list read_parasitics $spef] }
    if {$clocks eq "propagated"} { set_propagated_clock [all_clocks] }
    if {[sizeof_collection [get_supply_nets -quiet *]]} {
        error "SDC/session already contains supply nets; this runner supports the project's single primary supply flow."
    }
    create_power_domain AUTO_SCALING_TOP
    create_supply_net $rail -domain AUTO_SCALING_TOP
    create_supply_net $gnd -domain AUTO_SCALING_TOP
    set_domain_supply_net AUTO_SCALING_TOP -primary_power_net $rail -primary_ground_net $gnd
    set cells [get_cells -hierarchical -quiet *]
    check_status set_temperature [list set_temperature [dict get $plan t] -object_list $cells]
    check_status set_voltage [list set_voltage [dict get $plan v] -object_list $rail]
    check_status set_ground [list set_voltage 0.0 -object_list $gnd]
    check_status update_timing {update_timing -full}
    set paths [get_timing_paths -delay_type $dt -max_paths 1]
    if {![sizeof_collection $paths]} { error "No timed path at the target condition; inspect constraints and linking." }
    redirect -file ${out}.libgroups { report_lib_groups -scaling -show {voltage temperature} }
    report_fixed_paths $out [dict get $fixed paths] $dt [option $cfg pba_mode ""]
    if {![file exists $out] || [file size $out] == 0} { error "No timing report produced: $out" }
    # Select a real adjacent input/output pair on a timing path, not all cell pins.
    set arc_found 0
    if {[sizeof_collection $paths]} {
        set prev ""
        foreach_in_collection point [get_attribute [index_collection $paths 0] points] {
            set pin [get_attribute $point object]
            if {$prev ne ""} {
                set a [get_cells -quiet -of_objects $prev]
                set b [get_cells -quiet -of_objects $pin]
                if {[sizeof_collection $a] == 1 && [sizeof_collection $b] == 1 &&
                    [get_object_name $a] eq [get_object_name $b] &&
                    [get_attribute $prev direction] eq "in" && [get_attribute $pin direction] eq "out"} {
                    redirect -file ${out}.dcalc { report_delay_calculation -from $prev -to $pin }
                    set arc_found 1
                    break
                }
            }
            set prev $pin
        }
    }
    if {!$arc_found} { puts "WARNING: No cell arc found for .dcalc; inspect the timing report." }
    puts "DONE: $out (PT session remains open)"
    return $plan
}

# 1_union.py의 고정 경로/edge 의미와 출력 marker를 유지하는 내장 reporter.
proc auto_scaling::fixed_path_edge_opt {base_opt dir} {
  if {$dir eq "r"} {
    return "-rise_$base_opt"
  }
  if {$dir eq "f"} {
    return "-fall_$base_opt"
  }
  return "-$base_opt"
}

proc auto_scaling::report_fixed_paths {out_file paths delay_type pba_mode} {
    set measured 0
    set missing {}
    set idx 0
    foreach item $paths {
        incr idx
        lassign $item key from to through edges
        set pins [concat [list $from] $through [list $to]]
        set objects {}
        set bad_pin ""
        foreach pin $pins {
            set obj [get_pins -quiet $pin]
            if {[sizeof_collection $obj] != 1} { set bad_pin $pin; break }
            lappend objects $obj
        }
        set text ""
        set count 0
        if {$bad_pin ne ""} {
            set text "FIXED_PATH_STATUS: missing_or_ambiguous_pin $bad_pin"
        } else {
            set use_edges [expr {[llength $edges] == [llength $pins]}]
            set cmd [list report_timing -delay_type $delay_type -path_type full_clock_expanded \
                -max_paths 1 -sort_by slack -nets -input_pins -capacitance -transition_time \
                -nosplit -significant_digits 6]
            set i 0
            foreach obj $objects {
                if {$i == 0} { set base from } elseif {$i == [llength $objects]-1} {
                    set base to
                } else { set base through }
                set dir ""
                if {$use_edges} { set dir [lindex $edges $i] }
                lappend cmd [fixed_path_edge_opt $base $dir] $obj
                incr i
            }
            if {$pba_mode ne ""} { lappend cmd -pba_mode $pba_mode }
            if {[catch {redirect -variable text {eval $cmd}} problem]} {
                append text "\nFIXED_PATH_STATUS: report_error $problem"
            } else { set count [regexp -all -line {^\s*Startpoint:} $text] }
        }
        if {$count == 1} { incr measured } else { lappend missing $idx }
        redirect -append $out_file {
            puts "### FIXED_PATH idx=$idx key=$key"
            puts $text
            puts ""
        }
    }
    puts "FIXED PATHS RESULT: requested=$idx measured=$measured missing=[llength $missing]"
    if {[llength $missing]} {
        error "Incomplete fixed-path report: [llength $missing] paths failed; idx=$missing. Inspect $out_file; no replacement paths were selected."
    }
}

# USER SETTINGS의 단순 변수들을 내부 설정으로 변환합니다.
proc auto_scaling::build_config {} {
    foreach name {
        TARGET_PROCESS TARGET_VOLTAGE TARGET_TEMPERATURE SCALING_AXIS
        RC_CORNER ANALYSIS SI_ANALYSIS CLOCK_SETTING DB_FOLDER LIB_FOLDER
        TOP_MODULE NETLIST_FILE SDC_FILE SPEF_FOLDER SPEF_COMMON_NAME FIXED_PATH_FILE
        RESULT_FOLDER POWER_NET GROUND_NET
    } {
        if {![info exists ::$name]} { error "USER SETTINGS에 $name 항목이 없습니다." }
    }

    set analysis [string tolower $::ANALYSIS]
    switch -- $analysis {
        setup { set delay_type max }
        hold  { set delay_type min }
        default { error "ANALYSIS는 setup 또는 hold여야 합니다." }
    }

    set si_name [string tolower $::SI_ANALYSIS]
    switch -- $si_name {
        off { set si 0 }
        on  { set si 1 }
        default { error "SI_ANALYSIS는 off 또는 on이어야 합니다." }
    }

    set library_globs {}
    if {$::DB_FOLDER ne ""} { lappend library_globs [file join $::DB_FOLDER *.db] }
    if {$::LIB_FOLDER ne ""} { lappend library_globs [file join $::LIB_FOLDER *.lib] }
    if {![llength $library_globs]} { error "DB_FOLDER와 LIB_FOLDER 중 하나는 지정해야 합니다." }

    if {$::RC_CORNER eq ""} {
        set spef_template [file join $::SPEF_FOLDER "${::SPEF_COMMON_NAME}_{temp}.spef"]
    } else {
        set spef_template [file join $::SPEF_FOLDER "${::SPEF_COMMON_NAME}.{rc}_model_{temp}.spef"]
    }

    set voltage [number $::TARGET_VOLTAGE]
    set temperature [number $::TARGET_TEMPERATURE]
    set vtag [string map {. p - m} [format %.12g $voltage]]
    set ttag [string map {. p - m} [format %.12g $temperature]]
    set filename "scaled_[string toupper $::TARGET_PROCESS]_${vtag}V_${ttag}C_[string toupper $::SCALING_AXIS]_${analysis}"
    if {$::RC_CORNER ne ""} { append filename "_$::RC_CORNER" }
    append filename ".rpt"

    set cfg [dict create \
        library_globs $library_globs \
        target_process $::TARGET_PROCESS \
        target_v $voltage \
        target_t $temperature \
        target_rc $::RC_CORNER \
        mode $::SCALING_AXIS \
        top $::TOP_MODULE \
        verilog $::NETLIST_FILE \
        sdc $::SDC_FILE \
        spef_template $spef_template \
        clock_mode $::CLOCK_SETTING \
        delay_type $delay_type \
        si $si \
        fixed_tcl $::FIXED_PATH_FILE \
        rail_name $::POWER_NET \
        ground_name $::GROUND_NET \
        out_rpt [file join $::RESULT_FOLDER $filename]]
    return $cfg
}

# source하면 위 설정의 입력 선택만 확인합니다.
# run_scaling.tcl은 이 파일을 실행 없이 읽기 위해 load_only를 사용합니다.
if {![info exists ::auto_scaling_load_only] || !$::auto_scaling_load_only} {
    set scaling_config [auto_scaling::build_config]
    puts "CHECK: 라이브러리를 PT에 로드하거나 STA를 실행하지 않고 선택만 확인합니다."
    auto_scaling::plan $scaling_config
    puts "확인이 끝났습니다. 실제 실행은 run_scaling.tcl을 사용하세요."
}
