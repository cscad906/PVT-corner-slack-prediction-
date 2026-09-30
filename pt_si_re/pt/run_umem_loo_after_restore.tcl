# Execute native PrimeTime u_mem VDDPE leave-one-out after restore_session.
# First run prepare_umem_loo.tcl in the original grouped session. Then restore
# a session with the SAME design/fixed paths and libraries, but WITHOUT the
# original u_mem scaling group. Existing target-excluded core groups are OK.
# Edit USER SETTINGS in run_scaling_after_restore.tcl, then source this file.
# The generated group is checked before any timing update. A full-group
# restore_session fails with UML-019 instead of producing a false LOO report.

set ::auto_scaling_restored_load_only 1
source [file join [file dirname [info script]] run_scaling_after_restore.tcl]
unset ::auto_scaling_restored_load_only

set umem_loo_group_file [file join [file normalize $::RESULT_FOLDER] umem_loo_group.tcl]
if {![file isfile $umem_loo_group_file]} {
    error "UML-020: Run prepare_umem_loo.tcl first; missing $umem_loo_group_file"
}
source $umem_loo_group_file

set scaling_config [auto_scaling::build_restore_config]
dict set scaling_config create_missing_scaling_groups 1
set ordinary_report [dict get $scaling_config out_rpt]
dict set scaling_config out_rpt [file join [file dirname $ordinary_report] \
    "umem_loo_[file tail $ordinary_report]"]
set scaling_result [auto_scaling::run_config_with_log $scaling_config]
puts "U_MEM LOO REPORT: $scaling_result"
