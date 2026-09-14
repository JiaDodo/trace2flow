% SYNTHETIC DATA: deterministic fixture for the upstream pipeline smoke test.
% The run IDs in this file are reserved for compilation only. Holdout run IDs
% and values live in smoke_holdout.json so the test does not reuse train runs.

job("train_1").
job_status("train_1", "completed").
call("train_1", "lookup_1", "lookup_customer", "completed").
call("train_1", "update_1", "update_ticket", "completed").
spawned_by("train_1", "lookup_1", "decision_1").
spawned_by("train_1", "update_1", "decision_2").
depends("train_1", "decision_2", "decision_1").
param("train_1", "lookup_1", "source", "support_fixture").
param("train_1", "lookup_1", "customer_id", "customer_train_1").
param("train_1", "update_1", "status", "resolved").
param("train_1", "update_1", "ticket_id", "ticket_train_1").

job("train_2").
job_status("train_2", "completed").
call("train_2", "lookup_2", "lookup_customer", "completed").
call("train_2", "update_2", "update_ticket", "completed").
spawned_by("train_2", "lookup_2", "decision_1").
spawned_by("train_2", "update_2", "decision_2").
depends("train_2", "decision_2", "decision_1").
param("train_2", "lookup_2", "source", "support_fixture").
param("train_2", "lookup_2", "customer_id", "customer_train_2").
param("train_2", "update_2", "status", "resolved").
param("train_2", "update_2", "ticket_id", "ticket_train_2").

job("train_3").
job_status("train_3", "completed").
call("train_3", "lookup_3", "lookup_customer", "completed").
call("train_3", "update_3", "update_ticket", "completed").
spawned_by("train_3", "lookup_3", "decision_1").
spawned_by("train_3", "update_3", "decision_2").
depends("train_3", "decision_2", "decision_1").
param("train_3", "lookup_3", "source", "support_fixture").
param("train_3", "lookup_3", "customer_id", "customer_train_3").
param("train_3", "update_3", "status", "resolved").
param("train_3", "update_3", "ticket_id", "ticket_train_3").
