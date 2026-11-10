#!/usr/bin/env node
'use strict';
/* Synthetic failures only; never uses private original records. */
const assert=require('node:assert/strict');
const {settleFrozenPlan}=require('../scripts/boat_frozen_plan_settlement.cjs');
const circular={}; circular.self=circular;
const fail=settleFrozenPlan(circular,{},{}); // JSON.stringify -> native TypeError
assert.equal(fail.status,'HOLD');
assert.equal(fail.reason,'FROZEN_INPUT_REVIEW_REQUIRED');
assert.equal(fail.diagnostic_stage,'PLAN_INPUT');
assert.equal(fail.diagnostic_class,'TypeError');
assert.equal(fail.diagnostic_module,'FROZEN_SETTLEMENT');
assert.ok(Number.isInteger(fail.diagnostic_line)&&fail.diagnostic_line>0);
assert.equal(fail.diagnostic_caller_module,'FROZEN_SETTLEMENT');
assert.ok(Number.isInteger(fail.diagnostic_caller_line)&&fail.diagnostic_caller_line>0);
assert.equal(fail.scenarios.length,0);
assert.equal(fail.actual_purchases,false);
assert.equal(fail.promotion_allowed,false);
const reviewed=settleFrozenPlan({}, {}, {});
assert.equal(reviewed.status,'HOLD');
assert.equal(reviewed.reason,'REGISTRATION_REVIEW_REQUIRED');
assert.equal(Object.hasOwn(reviewed,'diagnostic_class'),false);
console.log(JSON.stringify({status:'FROZEN_NATIVE_DIAGNOSTIC_SYNTHETIC_TEST_PASSED',inputs_real:false,source_requests:0}));
