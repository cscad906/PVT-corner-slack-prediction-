# Run: tclsh pt_si_re/pt/tests/test_library_catalog_audit.tcl
# Regression: extra loaded voltages must be explained, never silently used
# across library sets/processes/temperatures or confused with PG-pin scope.
set test_dir [file dirname [info script]]
set ::auto_scaling_restored_load_only 1
source [file join $test_dir .. run_scaling_after_restore.tcl]
unset ::auto_scaling_restored_load_only
set failed [catch {source [file join $test_dir .. show_library_scaling_group.tcl]} reason]
if {!$failed || ![string match {Set LIBRARY_NAME*} $reason]} {
    error "Query definitions did not load with the expected blank-input error: $reason"
}

proc assert_contains {text part} {
    if {[string first $part $text] < 0} { error "Missing '$part' in query output:\n$text" }
}
proc assert_absent {text part} {
    if {[string first $part $text] >= 0} { error "Unexpected '$part' in query output" }
}
set ::fixture_rows {}
set ::fixture_libs [dict create]
foreach {name family process voltage temperature} {
    low MEM_RCMAX SSPG 0.475 25
    high MEM_RCMAX SSPG 0.685 25
    hot MEM_RCMAX SSPG 0.95 125
    fast MEM_RCMAX FF 0.825 25
    rcmin MEM_RCMIN SSPG 0.875 25
    revision MEM_RCMAX_REV2 SSPG 0.925 25
} {
    set path /fixture/${name}.db
    lappend ::fixture_rows [dict create file $path lib_name $name family $family \
        process $process v $voltage t $temperature]
    dict set ::fixture_libs $name $path
}
dict set ::fixture_libs unparsed /fixture/unparsed.db
dict set ::fixture_libs same_db_other_internal_name /fixture/high.db
dict set ::fixture_libs no_source ""
set ::fixture_catalog [dict create rows $::fixture_rows ignored [list \
    [dict create lib_name unparsed path /fixture/unparsed.db reason {ambiguous Operating Conditions}]]]
rename auto_scaling::catalog auto_scaling::original_catalog
proc auto_scaling::catalog {cfg} { return $::fixture_catalog }
proc sizeof_collection {items} { return [llength $items] }
proc foreach_in_collection {name objects body} {
    upvar 1 $name item
    foreach item $objects { uplevel 1 $body }
}
proc get_libs {args} {
    if {$args eq {-quiet *}} { return [dict keys $::fixture_libs] }
    if {[lrange $args 0 1] ne {-quiet -exact}} { error "Unexpected get_libs arguments: $args" }
    set wanted [lindex [lindex $args 2] 0]
    set result {}
    dict for {name path} $::fixture_libs {
        if {$wanted eq $name || $wanted eq "$path:$name"} { lappend result $name }
    }
    return $result
}
proc get_attribute {args} {
    set name [lindex $args end-1]
    switch -- [lindex $args end] {
        full_name { return $name }
        source_file_name { return [dict get $::fixture_libs $name] }
        extended_name { return "[dict get $::fixture_libs $name]:$name" }
        lib_scaling_group { return {} }
    }
    error "Unexpected attribute query: $args"
}
# Reject any timing, voltage, library-group, or PG-pin mutations/expensive scans.
foreach command {set_voltage set_temperature define_scaling_lib_group update_timing \
    read_db restore_session size_cell get_pg_pins get_supply_nets} {
    proc $command {args} { error "Read-only catalog audit must not call this command" }
}
rename puts original_puts
proc puts {args} { lappend ::output [lindex $args end] }
proc query_text {set_name} {
    set ::output {}
    library_scaling_group_report::show_library_set $set_name
    return [join $::output \n]
}

set ::scaling_config [dict create mode V target_process SSPG target_v 0.76 \
    target_t 25 fixed_library_set "" fixed_library_voltage nearest scaling_power_nets VDD_SCALE]
set original_config $::scaling_config
set text [query_text MEM_RCMAX]
assert_contains $text "raw_loaded=9 parsed=6 unparsed=1 not_cataloged=2"
assert_contains $text "members=3 other_set=2 same_set_other_process=1"
assert_contains $text "candidates=2 other_temperature=1 excluded_target=0 nearest_candidates=0"
assert_contains $text "all parsed sets/processes/temperatures; NOT scaling inputs): 0.475 0.685 0.825 0.875 0.925 0.95"
assert_contains $text "after_target_exclusion=0.475 0.685 lower=0.685 upper=NONE status=CANNOT_BRACKET"
assert_contains $text "RECORDED SET SCOPE: UNAVAILABLE"
assert_contains $text "UNPARSED: LIB=unparsed reason=ambiguous Operating Conditions"
assert_contains $text "LIB=same_db_other_internal_name reason=SOURCE_PATH_REUSED"
assert_contains $text "LIB=no_source reason=NO_SOURCE_FILE"
assert_absent $text "AUDIT LIB "
if {$::scaling_config ne $original_config} { error "Query changed scaling_config" }
original_puts "PASS: all loaded objects reconciled; other-set/process/T voltages not used as interpolation inputs; compact audit and raw catalog omissions explained"

set ::SHOW_ALL_LOADED_LIBRARIES 1
set text [query_text MEM_RCMAX]
assert_contains $text "lookup=OTHER_LIBRARY_SET v_input=NOT_EVALUATED process=SSPG voltage=0.875"
assert_contains $text "lookup=OTHER_PROCESS v_input=NOT_EVALUATED process=FF voltage=0.825"
assert_contains $text "lookup=SET_MEMBER v_input=OTHER_TEMPERATURE process=SSPG voltage=0.95"
assert_contains $text "lookup=SET_MEMBER v_input=V_INPUT_CANDIDATE process=SSPG voltage=0.475"
assert_contains $text "SET=MEM_RCMAX_REV2"
dict set ::scaling_config target_v 0.685
set text [query_text MEM_RCMAX]
assert_contains $text "candidates=1 other_temperature=1 excluded_target=1"
assert_contains $text "lookup=SET_MEMBER v_input=EXCLUDED_TARGET_POINT process=SSPG voltage=0.685"
assert_contains $text "after_target_exclusion=0.475 lower=0.475 upper=NONE status=CANNOT_BRACKET"
dict set ::scaling_config fixed_library_set MEM_RCMAX
set text [query_text MEM_RCMAX]
assert_contains $text "excluded_target=0 nearest_candidates=2"
assert_contains $text "status=NEAREST_DB_POLICY"
assert_contains $text "NEAREST DB CANDIDATE: voltage=0.685"
assert_contains $text "lookup=SET_MEMBER v_input=NEAREST_DB_CANDIDATE process=SSPG voltage=0.685"
dict set ::scaling_config fixed_library_voltage 0.685
set text [query_text MEM_RCMAX]
assert_contains $text "nearest_candidates=0 fixed_restore=2"
assert_contains $text "status=EXPLICIT_FIXED_SET"
original_puts "PASS: detailed reasons, ordinary target exclusion, exact-target nearest eligibility and numeric restore policy remain distinct"

# Scope comes from actual linked DB identity and cached PG classification,
# never from the voltage-range display. Reading it must not rescan PG pins.
set context $::scaling_config
set fixed_result [dict create family_matches {MEM_RCMAX MEM_RCMIN} \
    used_library_keys [list [list /fixture/high.db high] [list /fixture/rcmin.db rcmin]]]
set target_result [dict create family_matches MEM_RCMIN \
    used_library_keys [list [list /fixture/rcmin.db rcmin]]]
set ::auto_scaling::last_library_scope [dict create context $context design_name "" \
    rows $::fixture_rows fixed_result $fixed_result rail_result $target_result]
set text [query_text MEM_RCMAX]
assert_contains $text "RECORDED SET SCOPE: FIXED_RAIL_ONLY"
assert_contains $text "SCOPE LINKED LIB: high"
assert_absent $text "SCOPE LINKED LIB: low"
set text [query_text MEM_RCMIN]
assert_contains $text "RECORDED SET SCOPE: TARGET_RAIL_MATCH"
assert_contains $text "SCOPE LINKED LIB: rcmin"
set text [query_text MEM_RCMAX_REV2]
assert_contains $text "RECORDED SET SCOPE: NOT_USED_BY_FIXED_PATHS"
dict set ::scaling_config target_v 0.76
set text [query_text MEM_RCMAX]
assert_contains $text "RECORDED SET SCOPE: UNAVAILABLE (scaling configuration changed since planning)"
set ::auto_scaling::last_library_scope {}
original_puts "PASS: fixed-rail, target-rail and outside-path recorded scope; actual linked DB only; changed config rejected without PG rescans"

set ::SHOW_ALL_LOADED_LIBRARIES 0
set ::output {}
set failed [catch {library_scaling_group_report::show_library_set absent} reason]
if {!$failed || ![string match {*found 0*} $reason]} { error "Missing-set query not rejected" }
assert_contains [join $::output \n] "CATALOG AUDIT: raw_loaded=9"
set ::SHOW_ALL_LOADED_LIBRARIES invalid
set failed [catch {query_text MEM_RCMAX} reason]
if {!$failed || ![string match {LG-002:*} $reason]} { error "Invalid detail option not rejected" }
original_puts "PASS: absent-set and invalid-option errors; no PG queries, group changes, relinks, V/T changes or timing updates"
original_puts "ALL LIBRARY CATALOG AUDIT TESTS PASSED"
