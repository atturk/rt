import assert from 'node:assert/strict';
import test from 'node:test';
import { launchMessage } from '../lib/launch.js';

test('only study commands in private chats open the authenticated Mini App', () => {
  const message = { text: '/app', chat: { id: 123, type: 'private' } };
  const reply = launchMessage(message, 'https://study.example/mini-app.html');
  assert.equal(reply.reply_markup.inline_keyboard[0][0].web_app.url, 'https://study.example/mini-app.html');
  assert.equal(launchMessage({ ...message, text: 'my answer' }, 'https://study.example'), null);
  assert.equal(launchMessage(message, 'http://localhost'), null);
  assert.equal(launchMessage(message, ''), null);
});

test('forum chats get instructions in their topic instead of an unsupported web_app button', () => {
  const reply = launchMessage({ text: '/recall@rt_bot', chat: { id: -123, type: 'supergroup' }, message_thread_id: 10 }, 'https://study.example');
  assert.equal(reply.message_thread_id, 10);
  assert.equal(reply.reply_markup, undefined);
});
