# Run: tclsh pt_si_re/pt/tests/test_loo_target_guard.tcl
# LOO guards TL-001 (cell linked to a target-corner DB) and TL-003 (target-corner
# DB inside an active scaling group used by the design). Read-only fixtures.
set ::auto_scaling_restored_load_only 1
source [file join [file dirname [info script]] .. run_scaling_after_restore.tcl]
unset ::auto_scaling_restored_load_only

proc check {condition message} { if {!$condition} { error $message } }
proc expect_error {script pattern} {
    if {![catch {uplevel 1 $script} reason]} { error "Expected error $pattern" }
    if {![string match $pattern $reason]} { error "Wrong error: $reason (expected $pattern)" }
    return $reason
}
proc read_file {path} {
    set fp [open $path r]
    set text [read $fp]
    close $fp
    return $text
}

# Collections are plain lists of library names here.
proc sizeof_collection {items} { return [llength $items] }
proc get_object_name {items} { return $items }
proc foreach_in_collection {name objects body} {
    upvar 1 $name item
    foreach item $objects {
        set code [catch {uplevel 1 $body} result options]
        if {$code == 3} { break }
        if {$code == 4} { continue }
        # Like the real command, a return inside the body leaves the caller.
        if {$code == 2} { return -level 2 $result }
        if {$code != 0} { return -options $options $result }
    }
}
proc add_to_collection {group lib} { return [concat $group [list $lib]] }
proc get_libs {args} { return [dict keys $::lib_db] }
proc get_attribute {args} {
    set object [lindex $args end-1]
    set attr [lindex $args end]
    switch -- $attr {
        full_name { return $object }
        source_file_name { return [dict get $::lib_db $object] }
        min_source_file_name { return [expr {[dict exists $::min_db $object] ? [dict get $::min_db $object] : ""}] }
        lib_scaling_group { return [expr {[dict exists $::groups $object] ? [dict get $::groups $object] : ""}] }
        lib_cell {
            set result {}
            foreach cell $object { lappend result [dict get $::cell_lib $cell] }
            return $result
        }
    }
    error "Unknown attribute $attr"
}
foreach command {set_voltage set_temperature define_scaling_lib_group update_timing size_cell} {
    proc $command {args} { error "LOO checks must be read-only" }
}

# Catalog: CORE grid on the scaling rail; IO is a one-point library on another
# rail that happens to sit at the target voltage; AON is a grid on another rail.
set ::lib_db [dict create]
set rows {}
foreach {name process family v t} {
    CORE_054    SSPG core_pvt 0.54  25
    CORE_0685   SSPG core_pvt 0.685 25
    CORE_069    SSPG core_pvt 0.69  25
    CORE_08     SSPG core_pvt 0.8   25
    CORE_T125   SSPG core_pvt 0.685 125
    CORE_FF     FF   core_pvt 0.685 25
    IO_0685     SSPG io_pvt   0.685 25
    AON_0685    SSPG aon_pvt  0.685 25
    AON_09      SSPG aon_pvt  0.9   25
} {
    dict set ::lib_db $name /fixture/$name.db
    lappend rows [dict create file /fixture/$name.db process $process v $v t $t \
        family $family lib_name $name]
}
proc make_plan {rows linked} {
    set keys {}
    foreach name $linked { lappend keys [list /fixture/$name.db $name] }
    return [dict create process SSPG v 0.685 t 25.0 mode V family {core_pvt} \
        catalog $rows design_library_keys $keys]
}
set tmp [file join [expr {[info exists ::env(TMPDIR)] ? $::env(TMPDIR) : "/tmp"}] loo_guard_test_[pid]]
set out [file join $tmp restored_report.rpt]
set evidence [auto_scaling::detail_path $out .loo_check.txt]
set supply [dict create path_cells {u_a u_b u_c}]
set ::cell_lib [dict create u_a CORE_054/INV u_b CORE_054/ND2 u_c IO_0685/BUF]
set ::min_db [dict create]
set ::groups [dict create]

# Target DBs: exact process/V/T only; one-point off-rail IO is not corner data,
# an off-rail grid (AON) is; other process/temperature never count.
set targets [auto_scaling::target_corner_rows [make_plan $rows {}]]
check [expr {[lsort [dict keys $targets]] eq {/fixture/AON_0685.db /fixture/CORE_0685.db}}] \
    "Wrong target-corner DB set: [dict keys $targets]"
puts "PASS: target-corner DB set = exact process/V/T, rail sets and voltage grids only"

# TL-001 pass: linked at a neighbour corner; the one-point IO DB is allowed.
set plan [make_plan $rows {CORE_054 IO_0685}]
set targets [auto_scaling::loo_check_linked $plan $supply $out]
check [expr {[dict size $targets] == 2}] "TL-001 pass returned wrong targets"
set text [read_file $evidence]
check [string match "*TARGET_CORNER_DBS_LOADED: 2*" $text] "Evidence lacks target DB count"
check [string match "*LINKED_TO_TARGET_DB: 0*" $text] "Evidence lacks TL-001 result"

# TL-001 fail: any design cell (not only fixed-path cells) linked to the target DB.
set ::cell_lib [dict create u_a CORE_0685/INV u_b CORE_054/ND2 u_c IO_0685/BUF]
set reason [expect_error {auto_scaling::loo_check_linked [make_plan $rows {CORE_054 CORE_0685}] $supply $out} {TL-001:*}]
check [string match "*CORE_0685*" $reason] "TL-001 did not name the linked target DB"
set text [read_file $evidence]
check [string match "*TL-001 TARGET_DB_LINKED lib=CORE_0685 via=source_file_name fixed_path_cells=1*" $text] \
    "TL-001 evidence lacks lib/cell count"
check [string match "*LOO_CHECK_STATUS: FAILED (TL-001)*" $text] "TL-001 evidence lacks FAILED status"
# Clock-tree only: no fixed-path cell uses the target DB, still a leak.
set ::cell_lib [dict create u_a CORE_054/INV u_b CORE_054/ND2 u_c IO_0685/BUF]
expect_error {auto_scaling::loo_check_linked [make_plan $rows {CORE_054 CORE_0685}] $supply $out} {TL-001:*}
check [string match "*fixed_path_cells=0*" [read_file $evidence]] "Off-path target link was not reported"
# Hold: a min-library mapping to the target DB is also a leak.
dict set ::min_db CORE_054 /fixture/CORE_0685.db
expect_error {auto_scaling::loo_check_linked [make_plan $rows {CORE_054}] $supply $out} {TL-001:*min_source_file_name*}
set ::min_db [dict create]
# No target DB loaded at all: passes.
set no_target_rows {}
foreach row $rows { if {[dict get $row lib_name] ni {CORE_0685 AON_0685}} { lappend no_target_rows $row } }
set targets [auto_scaling::loo_check_linked [make_plan $no_target_rows {CORE_054}] $supply $out]
check [expr {[dict size $targets] == 0}] "Absent target corner produced target DBs"
puts "PASS: TL-001 design-wide link, off-path link, min-library mapping, absent target corner"

# TL-003 pass: group without the target; 0.69 near 0.685 is not a false match.
set plan [make_plan $rows {CORE_054}]
set targets [auto_scaling::loo_check_linked $plan $supply $out]
dict set ::groups CORE_054 {CORE_08 CORE_069}
auto_scaling::loo_check_groups $plan $targets $out
set text [read_file $evidence]
check [string match "*ACTIVE_GROUPS_CHECKED: 1 GROUPS_WITH_TARGET_DB: 0*" $text] "TL-003 pass evidence wrong"
check [string match "*LOO_CHECK_STATUS: PASSED*" $text] "TL-003 pass lacks PASSED"
# TL-003 fail: the design's group contains the target DB.
set targets [auto_scaling::loo_check_linked $plan $supply $out]
dict set ::groups CORE_054 {CORE_0685 CORE_08}
expect_error {auto_scaling::loo_check_groups $plan $targets $out} {TL-003:*CORE_0685.db*}
set text [read_file $evidence]
check [string match "*TL-003 TARGET_DB_IN_GROUP linked_lib=CORE_054 members=3*" $text] "TL-003 evidence lacks group"
check [string match "*LOO_CHECK_STATUS: FAILED (TL-003)*" $text] "TL-003 evidence lacks FAILED"
# A group member without a source DB cannot prove exclusion.
set targets [auto_scaling::loo_check_linked $plan $supply $out]
dict set ::lib_db GHOST ""
dict set ::groups CORE_054 {CORE_08 GHOST}
expect_error {auto_scaling::loo_check_groups $plan $targets $out} {TL-003:*source_file_name*}
dict unset ::lib_db GHOST
# Groups of libraries the design does not use are not checked.
set targets [auto_scaling::loo_check_linked $plan $supply $out]
dict set ::groups CORE_054 {CORE_08}
dict set ::groups CORE_069 {CORE_0685 CORE_08}
auto_scaling::loo_check_groups $plan $targets $out
puts "PASS: TL-003 path-based group check, no rounding false match, missing-source rejection, unused groups ignored"

# Text check in reuse mode: a group that no design cell links cannot affect
# timing, so a target-voltage line in it is reported but does not stop.
proc redirect {args} {
    set index [lsearch -exact $args -variable]
    upvar 1 [lindex $args [expr {$index+1}]] output
    set output [uplevel 1 [lindex $args end]]
}
proc report_lib_groups {args} {
    set lib [lindex $args [expr {[lsearch -exact $args -objects]+1}]]
    if {[string match LS_* $lib]} {
        return "Group 2\n    LS_A   25.00   { VDDI:0.685 VDDO:0.685 }   1.00\n    LS_B   25.00   { VDDI:0.75 VDDO:0.75 }   1.00\n"
    }
    return "Group 1\n    CORE_054   25.00   0.54   1.00\n    CORE_08   25.00   0.80   1.00\n"
}
foreach name {LS_A LS_B} { dict set ::lib_db $name /fixture/$name.db }
set ::groups [dict create CORE_054 {CORE_08} LS_A {LS_B} LS_B {LS_A}]
set relevant_rows {}
foreach name {CORE_054 CORE_08 LS_A LS_B} {
    lappend relevant_rows [dict create file /fixture/$name.db lib_name $name]
}
set all_text "[report_lib_groups -objects CORE_054][report_lib_groups -objects LS_A]"
set plan [dict create scaling_library_rows $relevant_rows fixed_library_rows {} \
    design_library_keys [list [list /fixture/CORE_054.db CORE_054]]]
check [expr {![auto_scaling::report_has_unapproved_corner $all_text $plan VDD 0.685 25]}] \
    "An unused group stopped the run"
dict set plan design_library_keys [list [list /fixture/CORE_054.db CORE_054] [list /fixture/LS_A.db LS_A]]
check [auto_scaling::report_has_unapproved_corner $all_text $plan VDD 0.685 25] \
    "A used group holding the target was not caught"
check [string match "*matched VDDI:0.685*" $::auto_scaling::last_corner_detail] \
    "Stop detail lacks the matched rail: $::auto_scaling::last_corner_detail"
dict unset plan design_library_keys
check [auto_scaling::report_has_unapproved_corner $all_text $plan VDD 0.685 25] \
    "Without design keys the old full check must still stop"
puts "PASS: reuse-mode group check ignores groups no design cell links, still stops on used ones"

file delete -force $tmp
puts "ALL LOO TARGET GUARD TESTS PASSED"
