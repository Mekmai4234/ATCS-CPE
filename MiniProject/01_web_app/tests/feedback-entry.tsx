import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import AnswerFeedback, { type Feedback } from '../src/AnswerFeedback';
function Harness() {
  const [value, setValue] = useState<Feedback | null>(null);
  const [fail, setFail] = useState(false);
  const [calls, setCalls] = useState(0);
  return (
    <>
      <button onClick={() => setFail(!fail)}>Toggle failure</button>
      <output>{calls}</output>
      <AnswerFeedback
        messageId="assistant-1"
        value={value}
        onSaved={setValue}
        port={{
          save: async (_, next) => {
            setCalls((n) => n + 1);
            if (calls === 0 && new URLSearchParams(location.search).has('hold')) {
              await new Promise<void>((resolve) =>
                window.addEventListener('release-feedback', () => resolve(), { once: true }),
              );
            } else await new Promise((r) => setTimeout(r, 150));
            if (fail) throw new Error('fixture');
            return next;
          },
        }}
      />
    </>
  );
}
createRoot(document.getElementById('root')!).render(<Harness />);
