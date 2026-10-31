import { createRoot } from 'react-dom/client';
import App from '../src/App';
import ChatReviewAdmin from '../src/ChatReviewAdmin';
import { Api } from '../src/api';
import { demoTransport } from '../src/demo';
let notes = 'existing review note',
  status = 'new';
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
const fallback = demoTransport();
const api = new Api('', async (input, init) => {
  const path = String(input);
  if (path.startsWith('/api/admin/chat-messages?'))
    return json({ items: [{ message_id: 'normal' }], total: 1 });
  if (path.startsWith('/api/admin/chat-reviews?'))
    return json({
      items: [{ case_id: 'case', question_excerpt: 'question', status }],
      total: 1,
      stats: {},
    });
  if (path === '/api/admin/chat-reviews/case' && init?.method === 'PATCH') {
    const data = JSON.parse(String(init.body));
    notes = data.notes;
    status = data.status;
    return json(data);
  }
  if (path === '/api/admin/chat-reviews/case')
    return json({
      case: { case_id: 'case', status, notes },
      question: { content: 'question' },
      answer: { content: 'answer' },
      moderation: {
        action: 'review_signal',
        draft: 'PRIVATE_SIGNAL_METADATA',
        visible_to_user: false,
      },
    });
  if (path === '/api/admin/chat-messages/normal')
    return json({
      case: null,
      question: { content: 'normal question' },
      answer: { content: 'normal answer' },
      visibility: 'published',
    });
  if (path === '/api/chat/check')
    return json(
      document.documentElement.dataset.resumeCount
        ? { decision: 'warn', message: 'confirm frozen request', acknowledgment_token: 'fresh' }
        : { decision: 'allow' },
    );
  if (path === '/api/chat' && init?.method === 'POST')
    return json({ job_id: 'paused', state: 'queued' }, 202);
  if (path === '/api/jobs/paused')
    return json({
      job_id: 'paused',
      kind: 'chat',
      state: 'paused',
      stage: 'paused',
      error_code: 'quota_wait',
      result: null,
    });
  if (path === '/api/jobs/paused/resume') {
    const count = Number(document.documentElement.dataset.resumeCount || 0) + 1;
    document.documentElement.dataset.resumeCount = String(count);
    if (count === 1) return json({ error: { code: 'moderation_confirmation_required' } }, 422);
    if (JSON.parse(String(init?.body)).moderation_token !== 'fresh')
      throw new Error('wrong acknowledgement');
    return json({ job_id: 'replacement', state: 'queued' }, 202);
  }
  if (path === '/api/jobs/replacement')
    return json({
      job_id: 'replacement',
      kind: 'chat',
      state: 'completed',
      stage: 'completed',
      result: { answer: 'RESUMED ANSWER', citations: [], status: 'insufficient_evidence' },
    });
  return fallback(input, init);
});
api.chatPolicyAvailable = true;
createRoot(document.getElementById('root')!).render(
  new URLSearchParams(location.search).has('admin') ? (
    <ChatReviewAdmin api={api} />
  ) : (
    <App
      api={api}
      member={{
        id: 'fixture',
        name: 'Fixture',
        email: 'fixture@example.test',
        role: 'user',
        status: 'active',
      }}
    />
  ),
);
