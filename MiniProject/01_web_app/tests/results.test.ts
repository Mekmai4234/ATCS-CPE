import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ResultView } from '../src/Results';
import ProviderNotice from '../src/ProviderNotice';
import type { TaskResult } from '../src/types';

it.each([
  ['gemini', 'Gemini'],
  ['ollama', 'AI ในเครื่อง'],
  ['answer-cache', 'ผลที่บันทึกไว้ (cache)'],
  ['unknown', 'ยังไม่ทราบผู้ให้บริการ'],
])('displays observed provider %s without guessing', (provider, expected) => {
  const html = renderToStaticMarkup(
    createElement(ProviderNotice, {
      metadata: {
        provider,
        requested_model: 'requested',
        returned_model: 'actual',
        latency_ms: 123.4,
      },
    }),
  );
  expect(html).toContain(expected);
  expect(html).toContain('actual');
  if (provider === 'answer-cache') expect(html).not.toContain('123 ms');
  else expect(html).toContain('123 ms');
  expect(html).not.toContain('requested');
});

const result: TaskResult = {
  status: 'insufficient_evidence',
  answer: 'ยังไม่มีป้ายระบุผู้ร้อง',
  coverage: {
    expected_videos: 1,
    processed_videos: 1,
    expected_chunks: 13,
    processed_chunks: 13,
    complete: true,
    notes: [],
  },
  citations: [
    {
      citation_id: '1',
      chunk_id: 'checked',
      video_id: 'dQw4w9WgXcQ',
      title: 'Checked caption',
      url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s',
      start_seconds: 10,
      end_seconds: 20,
    },
  ],
};

describe('checked evidence is distinct from a supported answer', () => {
  it('shows full inspection with insufficient evidence and checked source links', () => {
    const html = renderToStaticMarkup(createElement(ResultView, { result }));
    expect(html).toContain('ตรวจข้อมูลครบแล้ว แต่ยังยืนยันคำตอบไม่ได้');
    expect(html).toContain('แหล่งข้อมูลที่ตรวจสอบ');
    expect(html).toContain('watch?v=dQw4w9WgXcQ&amp;t=10s');
    expect(html).not.toContain('ข้อมูลยังไม่ครอบคลุมทั้งหมด');
  });
  it('keeps supported answer sources labelled as evidence', () => {
    const html = renderToStaticMarkup(
      createElement(ResultView, {
        result: { ...result, status: 'answered' },
      }),
    );
    expect(html).toContain('หลักฐานจากคลิป');
    expect(html).not.toContain('ยังยืนยันคำตอบไม่ได้');
  });
});

it('labels native video observations separately from transcript citations', () => {
  const native: TaskResult = {
    ...result,
    status: 'answered',
    citations: result.citations!.map((c) => ({ ...c, kind: 'video' })),
  };
  const html = renderToStaticMarkup(createElement(ResultView, { result: native }));
  expect(html).toContain('ภาพและเสียง · AI วิเคราะห์');
  expect(html).not.toContain('>บทถอดเสียง<');
});

it('withheld results never render draft text, citations or feedback', () => {
  const markup = renderToStaticMarkup(
    createElement(ResultView, {
      result: {
        ...result,
        visibility: 'withheld',
        assistant_message_id: 'saved',
        answer: 'PRIVATE_DRAFT_TEXT',
      },
    }),
  );
  expect(markup).not.toContain('PRIVATE_DRAFT_TEXT');
  expect(markup).not.toContain('youtube.com');
  expect(markup).not.toContain('ความคิดเห็นต่อคำตอบ');
  expect(markup).toContain('ระบบระงับคำตอบนี้');
});
