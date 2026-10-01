import { api } from 'sdk';
import { MINI_APP_URL } from 'lib/config';
import { launchMessage } from 'lib/launch';

export default async function (message) {
  const reply = launchMessage(message, MINI_APP_URL);
  if (reply) await api.sendMessage(reply);
}
