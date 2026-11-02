import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ArtifactView, ResultView } from '../src/Results';
import ProviderNotice from '../src/ProviderNotice';
import type { TaskResult } from '../src/types';

it.each([
  ['gemini', 'Gemini'],
  ['ollama', 'AI ในเครื่อง'],
  ['answer-cache', 'ผลที่บันทึกไว้ (cache)'],
  ['ollama-cache', 'ผลที่บันทึกไว้จาก AI ในเครื่อง (cache)'],
  ['gemini-cache', 'ผลที่บันทึกไว้จาก Gemini (cache)'],
  ['ollama,ollama-cache', 'AI ในเครื่อง'],
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
  if (provider.includes('-cache')) expect(html).not.toContain('123 ms');
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

it.each([0, 0.2, 12.4])(
  'local excerpts distinguish retrieval time %s from model generation',
  (latency) => {
    const html = renderToStaticMarkup(
      createElement(ResultView, {
        result: {
          ...result,
          status: 'answered',
          provider_metadata: {
            provider: 'local-evidence',
            requested_model: 'none',
            latency_ms: latency,
          },
          coverage: { ...result.coverage!, complete: false, processed_videos: 0 },
        },
      }),
    );
    expect(html).toContain('ข้อความต้นทางที่ค้นพบ');
    expect(html).toContain('ไม่ได้สร้างคำตอบใหม่ด้วย AI');
    expect(html).toContain('ไม่ยืนยันว่าตรวจครบทั้งคลิป');
    expect(html).not.toContain('โมเดล: none');
    expect(html).not.toContain('คลิป 0/1');
    expect(html).not.toContain('เวลาประมวลผลที่บันทึก');
    expect(html).toContain(
      latency === 0 ? 'ไม่มีเวลาค้นที่วัดไว้ในผลเดิม' : 'เวลาค้นและตรวจหลักฐาน',
    );
  },
);

it.each(['none', 'system', 'transcript'])(
  'does not imply a configured model ran for %s',
  (provider) => {
    const html = renderToStaticMarkup(
      createElement(ProviderNotice, {
        metadata: {
          provider,
          requested_model: 'configured-but-not-called',
          latency_ms: 0,
        },
      }),
    );
    expect(html).not.toContain('configured-but-not-called');
    expect(html).not.toContain('0 ms');
  },
);

it.each(['document_metadata', 'document_transcript'] as const)(
  'renders %s provenance without inventing a timed interval',
  (kind) => {
    const html = renderToStaticMarkup(
      createElement(ResultView, {
        result: {
          ...result,
          status: 'answered',
          provider_metadata: { provider: 'local-document', requested_model: 'none', latency_ms: 1 },
          citations: [
            {
              ...result.citations![0],
              kind,
              document_id: 'source',
              document_version: 'a'.repeat(64),
              source_hash: 'b'.repeat(64),
              start_seconds: kind === 'document_metadata' ? null : 19,
              end_seconds: null,
              metadata_field: kind === 'document_metadata' ? 'artist' : null,
              document_line: kind === 'document_transcript' ? 31 : null,
            },
          ],
        },
      }),
    );
    expect(html).toContain('ตอบจากไฟล์');
    expect(html).not.toContain('โมเดล: none');
    expect(html).not.toContain('0:00–');
    if (kind === 'document_metadata') {
      expect(html).toContain('ข้อมูลเอกสาร · ไม่มีเวลาเสียง');
      expect(html).not.toContain('&amp;t=');
    } else {
      expect(html).toContain('ตั้งแต่ 0:19 · ไม่ทราบเวลาจบ');
      expect(html).toContain('บรรทัด 31');
      expect(html).toContain('&amp;t=19s');
    }
  },
);

it('names the primary model when a same-project fallback answered', () => {
  const html = renderToStaticMarkup(
    createElement(ProviderNotice, {
      metadata: {
        provider: 'gemini',
        requested_model: 'gemini-3.8-flash',
        returned_model: 'gemini-3.8-flash',
        latency_ms: 50,
        fallback_from: 'gemini-3.5-flash',
      },
    }),
  );
  expect(html).toContain('โมเดล: gemini-3.8-flash');
  expect(html).toContain('ใช้รุ่นสำรอง เพราะ gemini-3.5-flash ไม่พร้อมชั่วคราว');
});

it.each([undefined, null])('shows no fallback notice when the primary answered (%s)', (value) => {
  const html = renderToStaticMarkup(
    createElement(ProviderNotice, {
      metadata: {
        provider: 'gemini',
        requested_model: 'gemini-3.5-flash',
        returned_model: 'gemini-3.6-flash',
        latency_ms: 50,
        fallback_from: value,
      },
    }),
  );
  expect(html).not.toContain('รุ่นสำรอง');
});

it('renders model **bold** as bold text without raw asterisks', () => {
  const html = renderToStaticMarkup(
    createElement(ResultView, {
      result: { ...result, status: 'answered', answer: 'แผน\n- **วันที่ 1:** RAG <b>x</b>' },
    }),
  );
  expect(html).toContain('<strong>วันที่ 1:</strong>');
  expect(html).not.toContain('**');
  expect(html).toContain('&lt;b&gt;x&lt;/b&gt;');
});

it('says how much of the clip a finished partial research answer read', () => {
  const coverage = {
    expected_videos: 1,
    processed_videos: 1,
    expected_chunks: 370,
    processed_chunks: 194,
    complete: false,
    notes: [],
  };
  const finished = renderToStaticMarkup(
    createElement(ResultView, {
      result: { ...result, status: 'answered', answer: 'คำตอบ', coverage },
      partial: true,
      kind: 'research',
    }),
  );
  expect(finished).toContain('ได้คำตอบแล้ว — อ้างอิงเนื้อหาคลิป 194/370 ช่วง');
  const stopped = renderToStaticMarkup(
    createElement(ResultView, {
      result: { ...result, answer: 'การค้นคว้าหยุดก่อนเสร็จ ได้ผลเพียงบางส่วน (x)', coverage },
      partial: true,
      kind: 'research',
    }),
  );
  expect(stopped).toContain('ได้ผลบางส่วน — งานนี้ยังไม่สำเร็จครบถ้วน');
});

it('labels a study plan created by research as part of that result', () => {
  const plan = {
    artifact_id: 'a1',
    type: 'study_plan' as const,
    content: { days: [{ day: 1, topic: 'RAG', citations: [] }] },
    citations: [],
    coverage: {
      expected_videos: 1,
      processed_videos: 1,
      expected_chunks: 370,
      processed_chunks: 194,
      complete: false,
      notes: [],
    },
  };
  const research = renderToStaticMarkup(
    createElement(ResultView, {
      result: { ...result, status: 'answered', answer: 'คำตอบ', artifacts: [plan] },
      kind: 'research',
    }),
  );
  expect(research).toContain('แผนเรียนที่แนบมากับการค้นคว้า');
  expect(research).not.toContain('วางแผน<span');
  const direct = renderToStaticMarkup(createElement(ArtifactView, { artifact: plan }));
  expect(direct).toContain('วางแผน');
  expect(direct).not.toContain('ที่แนบมากับการค้นคว้า');
});
