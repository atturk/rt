export function launchMessage(message, url) {
  if (!/^\/(start|app|list|recall)(?:@\w+)?(?:\s|$)/.test(message.text || '')) return null;
  if (message.chat?.type !== 'private') return {
    chat_id: message.chat.id,
    ...(message.message_thread_id ? { message_thread_id: message.message_thread_id } : {}),
    text: 'Apri la chat privata con questo bot e invia /app per studiare con RT.',
  };
  // Plain JavaScript only: do not depend on browser/Node URL globals in the V8 SDK.
  if (!/^https:\/\/[A-Za-z0-9.-]+(?::\d+)?(?:\/[^\s<>]*)?$/.test(url || '')) return null;
  return {
    chat_id: message.chat.id,
    text: 'Recall, lezioni, unità didattiche e audio: apri RT per studiare.',
    reply_markup: { inline_keyboard: [[{ text: 'Apri RT', web_app: { url } }]] },
  };
}
