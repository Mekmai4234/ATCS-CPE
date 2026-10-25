import { describe, expect, it } from 'vitest';
import { Api, ApiError } from '../src/api';
import { jobStatus, jobWarning } from '../src/domain';
import type { Job } from '../src/types';
import { serviceMessage, userMessages } from '../src/userMessages';

describe('public service error messages', () => {
  it.each(['free_tier_unverified', 'free_model_unverified', 'quota_pending'])(
    'keeps %s out of failed and paused task copy',
    (code) => {
      const job = { state: 'failed', stage: 'failed', error_code: code } as Job;
      expect(jobWarning(job)).toBe(userMessages.aiUnavailable);
      expect(jobStatus({ ...job, state: 'paused', stage: 'paused' })).toContain(
        userMessages.aiUnavailable,
      );
      expect(jobWarning(job)).not.toMatch(/Gemini|Free Tier|โปรเจกต์|โมเดล|ผู้ดูแล/);
      expect(job.error_code).toBe(code);
    },
  );
  it('retains retry guidance without exposing provider or HTTP diagnostics', () => {
    expect(serviceMessage('generation_rate_limited', 429)).toBe(userMessages.busy);
    expect(serviceMessage('provider_unavailable', 503)).toBe(userMessages.unavailable);
    expect(serviceMessage('unrecognized_backend_error', 502)).toBe(userMessages.unavailable);
    expect(jobWarning({ state: 'failed', error_code: 'database_internal_detail' } as Job)).toBe(
      userMessages.failed,
    );
  });
  it('keeps underlying diagnostic fields intact for internal error handling', async () => {
    const api = new Api(
      '',
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: 'free_tier_unverified',
              message: 'Internal project verification details',
              request_id: 'diagnostic-request',
              retryable: false,
            },
          }),
          { status: 503, headers: { 'Content-Type': 'application/json' } },
        ),
    );
    let caught: ApiError | undefined;
    try {
      await api.submit('/api/chat', {}, 'diagnostic-key');
    } catch (error) {
      caught = error as ApiError;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect(caught).toMatchObject({
      code: 'free_tier_unverified',
      requestId: 'diagnostic-request',
      retryable: false,
    });
    expect(serviceMessage(caught!.code, caught!.status)).toBe(userMessages.aiUnavailable);
  });
});
