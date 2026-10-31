import { expect, it } from 'vitest';
import { Api } from '../src/api';
import { toWire, fromWire, feedbackReasons } from '../src/feedbackSession';
it('maps every Thai reason and keeps likes free of dislike details', () => {
  for (const reason of Object.keys(feedbackReasons)) {
    const value = { rating: 'dislike' as const, reason, comment: 'ข้อความ' };
    expect(fromWire(toWire(value))).toEqual(value);
  }
  expect(toWire({ rating: 'like', reason: 'อื่น ๆ', comment: 'old' })).toEqual({ rating: 'like' });
});
it('uses encoded stable IDs and negotiated CSRF for PUT and DELETE', async () => {
  const sent: RequestInit[] = [];
  const api = new Api(
    '',
    async (url, init) => {
      expect(String(url)).toContain('/api/messages/stable-id/feedback');
      sent.push(init!);
      return new Response(JSON.stringify({ message_id: 'stable-id', feedback: null }));
    },
    1000,
    { csrf: () => ({ header: 'X-CSRF-Token', token: 'csrf' }), onSessionExpired: () => {} },
  );
  await api.saveFeedback('stable-id', { rating: 'like' });
  await api.saveFeedback('stable-id', null);
  expect(sent.map((i) => i.method)).toEqual(['PUT', 'DELETE']);
  expect((sent[0].headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf');
  expect(sent[0].credentials).toBe('include');
  api.dispose();
});
