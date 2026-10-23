import test from 'node:test';
import assert from 'node:assert/strict';
import * as protocol from '../scripts/completion-dispatch-protocol.mjs';
test('bounded one-hop dispatch protocol is implemented',()=>{
 assert.equal(typeof protocol.dispatchOnce,'function');
 assert.equal(typeof protocol.validateReceiver,'function');
});
