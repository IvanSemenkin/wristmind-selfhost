import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chatBase, chatListPath, isTalkPath } from './chatSurface.ts';

test('chat-only routes preserve shared IDs and use their own history screen', () => {
  for (const path of ['/talk', '/talk/history', '/talk/shared-chat-id']) {
    assert.equal(chatBase(path), '/talk');
    assert.equal(chatListPath(path), '/talk/history');
  }
});
test('panel and unrelated paths keep the existing panel navigation', () => {
  for (const path of ['/chats', '/chats/shared-chat-id', '/main', '/talkative', '/v1/chats']) {
    assert.equal(chatBase(path), '/chats');
    assert.equal(chatListPath(path), '/chats');
    assert.equal(isTalkPath(path), false);
  }
});
